"""
爆款结构分析器 —— 纯规则实现，不依赖任何外部 API

职责（对应"选题发现 + 结构学习"）：
  1. 识别标题模式（数字/疑问/冲突/悬念/反差/清单）
  2. 判定选题类型（教程/焦虑/解读/叙事）
  3. 提取正文骨架（钩子 → 核心 → 分点 → 收尾）
  4. 聚合出「选题模板」，告诉你这个方向该写什么、怎么写

关键设计：只学"结构与选题角度"，不复制"表达"。
输出的 skeleton 是段落功能骨架（如"钩子:用痛点提问"），而非原文句子。
"""

import re
from collections import Counter

# ---------------- 分词（jieba 可选，缺失时退化为 n-gram） ----------------

try:
    import jieba
    import jieba.analyse
    _HAS_JIEBA = True
except Exception:
    _HAS_JIEBA = False

# 领域词表：保证这类专名不会被切碎
DOMAIN_WORDS = [
    "养老金", "退休金", "个人养老金", "资格认证", "静默认证", "养老保险", "社保卡",
    "养老金并轨", "视同缴费", "计发基数", "定额调整", "挂钩调整", "倾斜调整",
    "养老金上调", "补发", "待遇资格认证", "电子社保卡", "掌上12333",
    "黄昏恋", "空巢老人", "独居老人", "中老年", "夕阳红", "情感需求", "陪伴",
    "再婚", "遗产", "赡养", "子女反对", "骗局", "孤独", "丧偶", "老伴",
]

if _HAS_JIEBA:
    for _w in DOMAIN_WORDS:
        jieba.add_word(_w, freq=20000)

STOPWORDS = set("""
这个 那个 我们 你们 他们 她们 自己 什么 怎么 可以 因为 所以 但是 如果 就是 一个 一些 各种
没有 已经 还是 这样 那样 现在 时候 地方 问题 情况 大家 非常 真的 很多 不少 不是 而是
这些 那些 以及 通过 进行 对于 关于 由于 需要 能够 应该 可能 一定 其实 或者 并且 而且
今天 明天 昨天 最近 目前 现在 之后 之前 以后 以上 以下 其中 另外 同时 然后 那么
本文 小编 注意 提醒 建议 告诉 知道 了解 看看 一起 很多 更多 相关 内容 方式 方法 方面
就是 还有 只是 只要 无论 不管 虽然 即使 然而 因此 于是 总之 来说 而言 之类 等等
第一 第二 第三 第四 第五 首先 其次 最后 比如 例如 当然 确实 千万 一定 千万
""".split())

# 纯虚词/语气词，出现即剔除
PARTICLES = set("的 了 是 在 和 与 也 都 就 而 及 或 不 没 有 这 那 其 之 为 以 于 对 从 到 把 被 让 使 会 能 要 可 很 更 最 太 只 又 再 还 已 将 该 等 啊 呀 吧 呢 吗 哦 嗯 着 过 给 得 地".split())


def _jieba_tags(text, limit):
    try:
        return jieba.analyse.extract_tags(text, topK=limit * 3, allowPOS=("n", "nr", "ns", "nt", "nz", "vn", "v", "an", "a", "i"))
    except Exception:
        return []


def _ngram_tags(text, limit):
    """无 jieba 时的退化方案：n-gram + 边界过滤 + 长词优先"""
    text = re.sub(r"[^\u4e00-\u9fa5]+", " ", text)
    cand = Counter()
    for seg in text.split():
        for L in (4, 3, 2):
            for i in range(len(seg) - L + 1):
                w = seg[i:i + L]
                if w[0] in PARTICLES or w[-1] in PARTICLES:
                    continue
                if w in STOPWORDS:
                    continue
                cand[w] += L  # 长词加权
    picked, used = [], set()
    for w, _ in cand.most_common(200):
        if any(w in u or u in w for u in used):
            continue
        used.add(w)
        picked.append(w)
        if len(picked) >= limit:
            break
    return picked


# ---------------- 标题模式 ----------------

TITLE_RULES = [
    ("冲突型", r"骗局|陷阱|人财两空|自残|砍伤|诈骗|被骗|纠纷|告上法庭|杀人|血本无归|维权|闹心|痛心|后悔|警惕"),
    ("数字型", r"[0-9０-９一二三四五六七八九十]+\s*(类|个|条|件|种|点|步|问|招|大|岁|万|亿|元|%|％)"),
    ("疑问型", r"[?？]|为什么|怎么办|怎么查|如何|能不能|还能|吗\b|有没有"),
    ("悬念型", r"背后|真相|内情|原因|意味|深意|内幕|结果|竟然|原来|答案|看懂|说清"),
    ("反差型", r"竟然|居然|反而|比.{1,6}更|其实|并非|不是.{1,6}而是|越.{0,4}越|不如"),
    ("清单型", r"必看|收藏|一文读懂|盘点|清单|大全|指南|汇总|记牢|别错过"),
]

# ---------------- 选题类型 ----------------

TOPIC_RULES = [
    ("教程型", r"怎么|如何|查询|认证|办理|流程|步骤|教你|方法|入口|操作|攻略|指南|一键"),
    ("焦虑型", r"未涨|没到账|停发|别急|还能|等待|变化|下调|缩水|不够|焦虑|担心|少了|暂停"),
    ("解读型", r"政策|并轨|新规|调整|改革|通知|文件|意味着|解读|规定|制度|方案|统筹"),
    ("叙事型", r"大爷|大妈|阿姨|阿婆|老伯|某地|男子|女子|老人|夫妻|纪实|案例|事件|讲述"),
]

# ---------------- 正文骨架 ----------------

# 分点标记：一、 / 1. / ① / 第一 / - / 【】
BULLET_RE = re.compile(
    r"^\s*(?:[一二三四五六七八九十]+\s*[、.．)）]|[0-9]{1,2}\s*[、.．)）]|[①②③④⑤⑥⑦⑧⑨⑩]|第[一二三四五六七八九十]+|[（(][一二三四五六七八九十0-9]{1,2}[)）]|[【\[])\s*"
)

HOOK_WORDS = r"很多|不少|最近|你是不是|有没有|相信|注意|提醒|一定要|千万别|发现|身边|如今|现在|这些年"
CTA_WORDS = r"转发|收藏|关注|留言|评论|点个|点亮|分享|保存|点击|结尾|总结|希望|建议|欢迎"


def _norm_title(t):
    return re.sub(r"<[^>]+>", "", t or "").strip()


def detect_title_pattern(title):
    hits = [name for name, pat in TITLE_RULES if re.search(pat, title)]
    return hits[0] if hits else "平述型", hits


def detect_topic_type(text):
    scores = []
    for name, pat in TOPIC_RULES:
        n = len(re.findall(pat, text))
        if n:
            scores.append((n, name))
    if not scores:
        return "通用型", []
    scores.sort(reverse=True)
    return scores[0][1], [s[1] for s in scores]


def split_paragraphs(body):
    """按换行切段，去掉过短的噪音行"""
    parts = [p.strip() for p in re.split(r"\n+", body or "")]
    return [p for p in parts if len(p) >= 12]


def extract_skeleton(body):
    """
    输出段落功能骨架 —— 只描述"这段在干什么"，不保留原句。
    结构： [{role, desc, sample_len}]
    """
    paras = split_paragraphs(body)
    if not paras:
        return []

    skel = []
    n = len(paras)

    # 开头：钩子
    head = paras[0][:60]
    has_hook = bool(re.search(HOOK_WORDS, head))
    skel.append({
        "role": "钩子",
        "desc": "用痛点或疑问开场，让读者代入" if has_hook else "直接切入主题",
        "sample_len": len(paras[0]),
    })

    # 中段：分点 or 递进
    bullets = [p for p in paras if BULLET_RE.match(p)]
    mid = paras[1:-1] if n > 2 else []
    if bullets:
        # 提取分点的标题头（冒号/换行前的一小段）
        heads = []
        for b in bullets[:8]:
            h = re.split(r"[：:，,。！!？?]", BULLET_RE.sub("", b))[0].strip()
            if 2 <= len(h) <= 24:
                heads.append(h)
        skel.append({
            "role": "分点论证",
            "desc": "用 %d 个并列要点展开，便于扫读" % len(bullets),
            "points": heads[:8],
            "sample_len": sum(len(b) for b in bullets),
        })
    elif mid:
        skel.append({
            "role": "递进展开",
            "desc": "按 %d 段连续推进，逐步补足信息" % len(mid),
            "sample_len": sum(len(p) for p in mid),
        })

    # 结尾：收尾/引导
    tail = paras[-1][:80]
    has_cta = bool(re.search(CTA_WORDS, tail))
    skel.append({
        "role": "收尾引导",
        "desc": "总结+行动号召（转发/收藏/评论）" if has_cta else "自然收束，不做号召",
        "sample_len": len(paras[-1]),
    })
    return skel


GENERIC = set(["相关", "内容", "方式", "方法", "方面", "问题", "情况", "时候", "今天", "很多",
               "不少", "大家", "一定", "可以", "需要", "已经", "还是", "这样", "那样"])


def extract_tags(title, body, limit=8):
    """
    提取关键词：标题高权重 + 正文补充。
    优先用 jieba（带领域词表），不可用时退化为 n-gram。
    """
    title = title or ""
    body = body or ""
    text = (title + "。") * 3 + body[:3000]

    if _HAS_JIEBA:
        raw = _jieba_tags(text, limit)
    else:
        raw = _ngram_tags(text, limit)

    out, seen = [], set()
    for w in raw:
        w = (w or "").strip()
        if len(w) < 2 or w in STOPWORDS or w in GENERIC:
            continue
        if all(ch in PARTICLES for ch in w):
            continue
        if any(w in s or s in w for s in seen):
            continue
        seen.add(w)
        out.append(w)
        if len(out) >= limit:
            break
    return out




def analyze_article(art):
    """对单篇素材做完整分析"""
    title = _norm_title(art.get("real_title") or art.get("title") or "")
    body = art.get("body") or ""
    tp, all_tp = detect_title_pattern(title)
    tt, all_tt = detect_topic_type(title + "\n" + body[:800])
    return {
        "article_id": art.get("id"),
        "title_pattern": tp,
        "title_pattern_all": all_tp,
        "topic_type": tt,
        "topic_type_all": all_tt,
        "hooks": extract_title_hooks(title),
        "skeleton": extract_skeleton(body),
        "tags": extract_tags(title, body),
    }


def extract_title_hooks(title):
    """拆解标题为什么能吸引人 —— 输出可复用的『钩子手法』"""
    hooks = []
    if re.search(r"[0-9０-９一二三四五六七八九十]+\s*(类|个|条|件|种|点|步|问)", title):
        hooks.append("数字锚定：给出确定数量，降低阅读预期成本")
    if re.search(r"[?？]|为什么|怎么|如何|还能|吗\b", title):
        hooks.append("疑问悬置：用问句制造信息缺口")
    if re.search(r"骗局|陷阱|人财两空|自残|砍伤|被骗|纠纷|杀人|闹心|痛心|警惕", title):
        hooks.append("冲突拉满：用强对抗词触发风险警觉")
    if re.search(r"背后|真相|原因|意味|深意|内幕|看懂|说清", title):
        hooks.append("悬念前置：承诺揭示隐藏原因")
    if re.search(r"竟然|居然|反而|其实|比.{1,6}更|越.{0,4}越", title):
        hooks.append("反差制造：打破常识预期")
    if re.search(r"你|咱们|爸妈|老人|长辈", title):
        hooks.append("人称贴近：直接指向读者或读者关心的人")
    if re.search(r"别急|别慌|一定要|千万别|必看|收藏", title):
        hooks.append("语气强提示：制造紧迫感与行动指令")
    if not hooks:
        hooks.append("平述直给：不加修饰，靠话题本身吸引")
    return hooks


# ---------------- 聚合：选题模板 ----------------

def aggregate_template(articles, analyses):
    """
    把一个话题下的多篇素材聚合成「选题模板」：
      - 主导标题模式 / 选题类型分布
      - 高频钩子手法
      - 常见骨架范式
      - 高频关键词
    这正是"选题发现"的产出：告诉你这个方向现在什么写法最吃香。
    """
    if not analyses:
        return {"empty": True}

    tp = Counter(a.get("title_pattern") for a in analyses if a.get("title_pattern"))
    tt = Counter(a.get("topic_type") for a in analyses if a.get("topic_type"))
    hook = Counter()
    for a in analyses:
        for h in a.get("hooks", []):
            hook[h] += 1
    tag = Counter()
    for a in analyses:
        for t in a.get("tags", []):
            tag[t] += 1

    roles = Counter()
    for a in analyses:
        for s in a.get("skeleton", []):
            roles[s.get("role", "")] += 1

    return {
        "count": len(analyses),
        "title_patterns": tp.most_common(),
        "topic_types": tt.most_common(),
        "top_hooks": hook.most_common(6),
        "top_tags": tag.most_common(12),
        "skeleton_roles": roles.most_common(),
        "recommend": _recommend(tp, tt, tag),
    }


def _recommend(tp, tt, tag):
    """根据统计给出可执行的选题建议"""
    tips = []
    if tp:
        name, n = tp.most_common(1)[0]
        tips.append("标题优先用「%s」，该方向出现频率最高（%d 篇）。" % (name, n))
    if tt:
        name, n = tt.most_common(1)[0]
        tips.append("选题以「%s」为主，可优先产出此类内容。" % name)
    if len(tp) >= 2:
        second = tp.most_common(2)[1][0]
        tips.append("可与「%s」组合做差异化，避开同质竞争。" % second)
    kw = [w for w, _ in tag.most_common(3)]
    if kw:
        tips.append("核心关键词：%s。" % "、".join(kw))
    tips.append("注意：只借用结构与选题角度，正文须用公开信息重新组织并加入增量，不要改写原句。")
    return tips


if __name__ == "__main__":
    import json
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import db

    arts = db.list_articles(has_body=True, limit=50)
    print("待分析（有正文）素材：%d 篇" % len(arts))
    n = 0
    for a in arts:
        res = analyze_article(a)
        db.save_analysis(a["id"], res)
        n += 1
        print("  - [%s|%s] %s" % (res["title_pattern"], res["topic_type"], a["title"][:40]))
    print("已写入分析：%d" % n)
