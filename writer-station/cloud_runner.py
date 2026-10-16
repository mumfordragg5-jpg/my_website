# -*- coding: utf-8 -*-
"""
无人值守流水线 —— 把工作台的活搬到没有界面的环境（GitHub Actions / 计划任务）

跑的是同一套引擎，只是去掉界面：
    采集素材 → 选选题 → 补公开信息 → 出稿 → 推公众号草稿箱 → 重建选题看板

三条设计原则（都是被"定时任务挂掉还不知道为什么"逼出来的）：

  1. **不抛栈、不闷死**。每一步的成败都写进报告；能降级就降级。
     只有"整整一轮什么都没干成"才返回非 0 —— 这样 GitHub 会发失败邮件提醒你。
  2. **不重复劳动**。出过稿的素材会改状态，下一轮不再选中，避免每天推同一篇。
  3. **留痕**。报告同时写 stdout 和 $GITHUB_STEP_SUMMARY，在 Actions 页面直接看，
     不用点进日志翻。

用法：
    python cloud_runner.py --dry-run                      # 只诊断，什么都不动
    python cloud_runner.py --harvest --count 2 --push     # 完整一轮（主号）
    python cloud_runner.py --no-harvest --count 1 --push --account 2
"""

import argparse
import io
import os
import sys
import time
import traceback
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import db            # noqa: E402
import collector     # noqa: E402
import fetcher       # noqa: E402
import rewriter      # noqa: E402
import exporter      # noqa: E402
import wxpush        # noqa: E402
import harvest       # noqa: E402
import build_board   # noqa: E402

# 已经处理过的素材状态 —— 选稿时要跳过
DONE_STATUS = ("used", "drafted", "pushed")

# 增量信息查询词：这一步是"合法性的技术落点"，
# 成品里必须有原文没有的公开事实，才不是换词洗稿。
INCREMENT_QUERIES = {
    "养老金": ["养老金 最新政策", "养老金 调整 发放"],
    "老年人感情": ["老年人 情感需求", "独居老人 关爱服务"],
}


# ==================== 报告 ====================

class Report(object):
    def __init__(self):
        self.rows = []
        self.bad = 0

    def _add(self, icon, msg):
        line = "%s %s" % (icon, msg)
        self.rows.append(line)
        print(line)

    def ok(self, m):
        self._add("  ✅", m)

    def info(self, m):
        self._add("  ·", m)

    def warn(self, m):
        self.bad += 1
        self._add("  ⚠️", m)

    def fail(self, m):
        self.bad += 1
        self._add("  ❌", m)

    def head(self, m):
        self._add("###", m)

    def text(self):
        return "\n".join(self.rows)

    def summary_md(self, title, tail=""):
        body = self.text()
        body = body.replace("###", "##").replace("  ✅", "- ✅").replace(
            "  ·", "- ·").replace("  ⚠️", "- ⚠️").replace("  ❌", "- ❌")
        return "## %s\n\n%s\n\n%s\n" % (title, body, tail)


def flush_summary(md):
    """写进 GitHub Actions 的步骤摘要（本机跑时这个变量不存在，静默跳过）"""
    p = os.environ.get("GITHUB_STEP_SUMMARY")
    if not p:
        return
    try:
        with io.open(p, "a", encoding="utf-8") as f:
            f.write(md + "\n")
    except Exception as e:
        print("  [summary] 写入失败：%s" % e)


# ==================== 各步骤 ====================

def do_diag(rep):
    rep.head("0. 环境诊断")
    rep.info("时间：%s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    try:
        ip = wxpush.detect_egress_ip()
        rep.info("出口 IP（直连）：%s" % (ip or "检测失败"))
    except Exception as e:
        rep.warn("出口 IP 检测失败：%s" % e)

    p = wxpush.use_proxy()
    if p:
        try:
            pip = wxpush.detect_ip_through_configured_proxy()
        except Exception as e:
            pip = "检测失败(%s)" % e
        if pip and pip == "检测失败":
            rep.warn("WX_PROXY=%s 已配置，但经它取不到出口 IP —— 隧道可能没建起来" % p)
        else:
            rep.info("WX_PROXY=%s → 经它出去看到的是 %s" % (p, pip or "未知"))
            rep.info("↑ 这个 IP 必须已经在公众号后台的 IP 白名单里")
    else:
        rep.info("WX_PROXY 未配置 → 微信接口直连（本机模式）")

    s = db.get_settings()
    rep.info("LLM：base=%s model=%s key=%s"
             % (s.get("llm_base"), s.get("llm_model"),
                "已配置" if s.get("llm_key") else "★未配置（会降级成任务书）★"))

    try:
        for a in wxpush.account_status():
            rep.info("公众号「%s」：凭据=%s 固定封面=%s 来源=%s"
                     % (a["label"], "有" if a["configured"] else "无",
                        "有" if a["has_thumb"] else "无（改为自动生成）",
                        ",".join(a["sources"]) or "-"))
    except Exception as e:
        rep.warn("账号状态读取失败：%s" % e)

    try:
        rep.info("素材库：%s" % db.stats())
    except Exception as e:
        rep.fail("素材库不可用：%s" % e)
        raise


def do_harvest(topics, kw_per_topic, pages, delay, rep):
    """列表采集（搜狗搜索页）—— 只拿标题/摘要，这是素材主力"""
    rep.head("1. 采集素材")
    c = collector.Collector(delay)
    total = 0
    for topic in topics:
        kws = harvest.TOPIC_KEYWORDS.get(topic) or [topic]
        for kw in kws[:kw_per_topic]:
            try:
                items = []
                for page in range(1, pages + 1):
                    items += c._retry(c.search, kw, page)
                    time.sleep(c._jitter())
            except Exception as e:
                rep.warn("搜索「%s」失败：%s" % (kw, e))
                time.sleep(min(delay, 20))
                continue
            seen, dedup = set(), []
            for it in items:
                if it["title"] in seen:
                    continue
                seen.add(it["title"])
                it["topic"] = topic
                dedup.append(it)
            if dedup:
                n = db.upsert_articles(dedup[:20 * pages])
                total += n
                rep.ok("%s | %s → 拿到 %d 条，新增 %d 条" % (topic, kw, len(dedup), n))
            else:
                rep.warn("%s | %s → 一条都没解析出来（多半是页面结构变了或被拦）" % (topic, kw))
            time.sleep(delay)
    if total == 0:
        rep.warn("本轮没采到任何新素材。云端 IP 若被搜狗判定为风险 IP，就会是这个表现；"
                 "可改用 --no-harvest，用缓存里已有的素材出稿。")
    return total


def pick_candidates(topics, count, rep):
    """选题：优先"有正文"的，其次按话题轮转，保证每个方向都有产出"""
    rows = db.list_articles(limit=5000)
    pool = [a for a in rows if (a.get("status") or "candidate") not in DONE_STATUS]
    rep.info("候选池：%d 条（总素材 %d 条，已处理 %d 条）"
             % (len(pool), len(rows), len(rows) - len(pool)))
    if not pool:
        return []

    def rank(a):
        return (0 if (a.get("body_len") or 0) > 0 else 1, -(a.get("id") or 0))

    picked, chosen = [], set()
    for t in topics:
        sub = sorted([a for a in pool if (a.get("topic") or "") == t], key=rank)
        if sub:
            picked.append(sub[0])
            chosen.add(sub[0]["id"])
    for a in sorted([x for x in pool if x["id"] not in chosen], key=rank):
        if len(picked) >= count:
            break
        picked.append(a)

    picked = picked[:count]
    for a in picked:
        rep.info("选中：[%s] %s（正文 %d 字）"
                 % (a.get("topic"), (a.get("title") or "")[:34], a.get("body_len") or 0))
    return picked


def do_increments(topic, rep):
    qs = INCREMENT_QUERIES.get(topic) or ["%s 最新政策" % topic]
    try:
        inc = fetcher.gather_increments(qs, 4)
    except Exception as e:
        rep.warn("增量抓取异常（%s）：%s" % (topic, e))
        return []
    good = [x for x in inc if x.get("title")]
    if good:
        rep.info("增量信息：%s → 取到 %d 条公开事实" % (topic, len(good)))
    else:
        rep.warn("增量信息：%s → 一条都没取到（成品会缺「原文没有的信息」，"
                 "建议之后手工补）" % topic)
    return good


def do_draft(a, inc, word_count, rep):
    r = rewriter.generate(a["id"], topic=a.get("topic"), increments=inc,
                          word_count=word_count, use_llm=True)
    brief = (r.get("engine") or "").startswith("brief")
    rep.ok("出稿 #%s 《%s》引擎=%s 正文 %d 字"
           % (r["draft_id"], (r["title"] or "")[:30], r["engine"], len(r["body"] or "")))
    db.update_article_status(a["id"], "drafted")
    return r, brief


def do_push(r, account, rep):
    content = exporter.body_to_wechat_html(r["body"])
    res = wxpush.push_draft_account(account, r["title"], content,
                                    digest=wxpush.make_digest(r["body"]),
                                    cover_title=r["title"])
    for w in res.get("warnings") or []:
        rep.warn("正文检查：%s" % w)
    rep.ok("已入【%s】草稿箱：%s" % (res.get("account"), (res.get("title") or "")[:30]))
    try:
        db.update_draft(r["draft_id"], status="pushed",
                        wx_media_id=res.get("media_id", ""),
                        pushed_at=db.now())
        db.update_article_status(r["article_id"], "pushed")
    except Exception as e:
        rep.warn("回写推送状态失败（不影响草稿本身）：%s" % e)
    return res


def do_board(rep):
    rep.head("看板")
    args_backup = sys.argv[:]
    sys.argv = ["build_board.py", "--keep"]
    try:
        rc = build_board.main()
    except Exception as e:
        rep.warn("看板重建异常：%s" % e)
        return 1
    finally:
        sys.argv = args_backup
    if rc == 0:
        rep.ok("选题看板已重建")
    else:
        rep.warn("看板未重建（rc=%s）—— 库为空时会保留线上已有的那份，属正常" % rc)
    return rc


# ==================== 主流程 ====================

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topics", default="养老金,老年人感情")
    ap.add_argument("--harvest", dest="harvest", action="store_true")
    ap.add_argument("--no-harvest", dest="harvest", action="store_false")
    ap.add_argument("--kw-per-topic", type=int, default=2)
    ap.add_argument("--pages", type=int, default=1)
    ap.add_argument("--delay", type=float, default=15.0)
    ap.add_argument("--count", type=int, default=2, help="本轮出几篇稿")
    ap.add_argument("--word-count", type=int, default=1200)
    ap.add_argument("--push", dest="push", action="store_true")
    ap.add_argument("--no-push", dest="push", action="store_false")
    ap.add_argument("--account", default="1", help="1=主号 2=副号")
    ap.add_argument("--allow-brief-push", action="store_true",
                    help="允许把降级产生的「任务书」也推到草稿箱（默认不允许）")
    ap.add_argument("--board", dest="board", action="store_true")
    ap.add_argument("--no-board", dest="board", action="store_false")
    ap.add_argument("--dry-run", action="store_true")
    ap.set_defaults(harvest=True, push=True, board=True)
    a = ap.parse_args()

    topics = [t.strip() for t in (a.topics or "").split(",") if t.strip()]
    rep = Report()
    t0 = time.time()

    rep.head("写作台 · 无人值守 一轮")
    rep.info("参数：方向=%s 采集=%s 出稿=%d 篇 推送=%s 账号=%s 试运行=%s"
             % ("/".join(topics), a.harvest, a.count, a.push, a.account, a.dry_run))

    try:
        db.init()
    except Exception as e:
        print("素材库初始化失败：%s" % e)
        traceback.print_exc()
        return 1

    do_diag(rep)

    if a.dry_run:
        rep.head("结果")
        rep.info("--dry-run：只做诊断，未采集 / 未出稿 / 未推送。")
        flush_summary(rep.summary_md("写作台 · 试运行诊断", "_试运行模式，无任何写入。_"))
        return 0

    new_items = 0
    if a.harvest:
        try:
            new_items = do_harvest(topics, a.kw_per_topic, a.pages, a.delay, rep)
        except Exception as e:
            rep.fail("采集阶段异常：%s" % e)
            print(traceback.format_exc())

    rep.head("2. 出稿")
    drafts, briefs = [], []
    try:
        picked = pick_candidates(topics, a.count, rep)
    except Exception as e:
        rep.fail("选题失败：%s" % e)
        picked = []
    if not picked:
        rep.warn("没有可用素材可选（可能都出过稿了）—— 这轮不出稿。")

    for art in picked:
        inc = do_increments(art.get("topic") or "", rep)
        try:
            r, brief = do_draft(art, inc, a.word_count, rep)
            drafts.append(r)
            if brief:
                briefs.append(r)
        except Exception as e:
            rep.fail("出稿失败（素材 #%s）：%s" % (art.get("id"), e))
            print(traceback.format_exc())

    rep.head("3. 推草稿箱")
    pushed = 0
    if not a.push:
        rep.info("按参数跳过推送。")
    elif not drafts:
        rep.info("没有新草稿，无需推送。")
    else:
        for r in drafts:
            if (r.get("engine") or "").startswith("brief") and not a.allow_brief_push:
                rep.warn("跳过推送：这是降级的「任务书」而非成稿（引擎=%s）。"
                         "配好 LLM Key 后会正常出稿；确要推就加 --allow-brief-push。"
                         % r["engine"])
                continue
            try:
                do_push(r, a.account, rep)
                pushed += 1
            except wxpush.WxError as e:
                rep.fail("推送失败：%s" % e)
            except Exception as e:
                rep.fail("推送异常：%s" % e)
                print(traceback.format_exc())

    if a.board:
        do_board(rep)

    used = round(time.time() - t0, 1)
    rep.head("结果")
    rep.info("耗时 %.1fs；新增素材 %d；新草稿 %d；入草稿箱 %d；异常 %d 项"
             % (used, new_items, len(drafts), pushed, rep.bad))
    try:
        rep.info("库现状：%s" % db.stats())
    except Exception:
        pass

    tail = "_新素材 %d · 新草稿 %d · 入草稿箱 %d_%s" % (
        new_items, len(drafts), pushed,
        "（有降级稿）" if briefs else "")
    flush_summary(rep.summary_md("写作台 · 无人值守", tail))

    # 真的什么都没干成 → 返回非 0，让 GitHub 发失败邮件提醒（否则坏掉了也没人知道）
    if not drafts and new_items == 0:
        print("\n★ 本轮没有任何产出（无新素材、无新草稿），返回 1 以便你能收到提醒。")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
