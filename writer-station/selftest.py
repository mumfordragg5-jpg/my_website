"""端到端自测：分析 -> 增量 -> 生成草稿 -> 导出预览（结果写文件）"""
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import db
import analyzer
import fetcher
import rewriter
import exporter

log = []
def L(s=""):
    log.append(str(s))

db.init()
L("库状态: " + str(db.stats()))

arts = db.list_articles(has_body=True, limit=50)
L("有正文素材: %d 篇" % len(arts))
for a in arts:
    L("  #%s %s (%s)" % (a["id"], a["title"][:44], a.get("topic")))

if not arts:
    io.open(os.path.join(HERE, "selftest.txt"), "w", encoding="utf-8").write("\n".join(log))
    sys.exit(0)

# 选第一篇做全流程
a = arts[0]
L("")
L("=" * 60)
L("选用素材: #%s %s" % (a["id"], a["title"]))
L("原文正文长度: %d 字" % a["body_len"])

# 1) 结构分析
an = analyzer.analyze_article(a)
db.save_analysis(a["id"], an)
L("")
L("--- 结构分析 ---")
L("标题模式: %s" % an["title_pattern"])
L("选题类型: %s" % an["topic_type"])
L("钩子手法: %s" % " / ".join(an["hooks"]))
L("骨架: %s" % " -> ".join(s["role"] for s in an["skeleton"]))
L("关键词: %s" % "、".join(an["tags"]))

# 2) 话题模板
arts_t = db.list_articles(topic=a.get("topic"), has_body=True, limit=200)
ans = [x for x in (db.get_analysis(x["id"]) for x in arts_t) if x]
tpl = analyzer.aggregate_template(arts_t, ans)
L("")
L("--- 话题模板（%s）---" % a.get("topic"))
L("样本 %d 篇 | 标题模式: %s | 选题: %s" % (
    tpl["count"],
    "、".join("%s×%d" % (k, v) for k, v in tpl["title_patterns"]),
    "、".join("%s×%d" % (k, v) for k, v in tpl["topic_types"])))
for r in tpl["recommend"]:
    L("  → " + r)

# 3) 增量
L("")
L("--- 增量抓取 ---")
kw = "养老金 上调 政策" if "养老" in (a.get("topic") or "") else "老年人 情感需求"
inc = fetcher.gather_increments([kw], 4)
for it in inc:
    L("  · %s | %s" % (it.get("title", "")[:50], it.get("source", "")))
L("共 %d 条增量" % len(inc))

# 4) 生成草稿（任务书模式，无需 API Key）
L("")
L("--- 生成草稿 ---")
r = rewriter.generate(a["id"], template=tpl, increments=inc, use_llm=False)
L("草稿 ID: %s | 引擎: %s" % (r["draft_id"], r["engine"]))
L("标题(锁定): %s" % r["title"])
L("正文预览:")
for line in (r["body"] or "").splitlines()[:40]:
    L("    " + line)

# 5) 导出
frag = exporter.draft_to_html(r["title"], r["body"])
page = exporter.build_page(r["title"], r["body"], "本地预览 · " + (r["topic"] or ""))
p = os.path.join(HERE, "preview.html")
io.open(p, "w", encoding="utf-8").write(page)
L("")
L("--- 导出 ---")
L("公众号 HTML 片段: %d 字符" % len(frag))
L("预览页: %s" % p)

L("")
L("最终库状态: " + str(db.stats()))
io.open(os.path.join(HERE, "selftest.txt"), "w", encoding="utf-8").write("\n".join(log))
print("done")
