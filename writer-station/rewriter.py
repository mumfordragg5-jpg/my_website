"""
改写引擎

三条硬规则（对应"只学结构、不做搬运"）：
  1. 标题锁定 —— 标题作为独立字段原样保留，不参与改写、不被模型改动
  2. 结构参考 —— 只把爆款的「骨架/钩子手法」给模型，不给原文句子
  3. 增量强制 —— 必须把抓到的公开信息写进去，成品要有独立信息价值

两种工作模式：
  LLM 模式    —— 配置了 OpenAI 兼容 API 时，直接产出成稿
  任务书模式  —— 未配置时，产出一份可执行的「写作任务书」，人工或后续补写

合规声明会被写进 prompt：禁止逐句改写、禁止照搬原文表达。
"""

import json
import re
import urllib.request

import db
import analyzer

SYSTEM_PROMPT = """你是一位服务于中老年读者及其子女的中文新媒体编辑，擅长把政策类、情感类话题写成通俗易懂的公众号文章。

写作要求：
1. 语言口语化、多用短句、多分段，一段不超过 4 行；关键信息用小标题或加粗突出。
2. 面向 50-70 岁读者，避免专业术语与生僻词；涉及办事流程要写到"点哪里、填什么"的程度。
3. 结构清晰：开头一句抓住痛点 → 中间分点讲透 → 结尾给一句实在的提醒或行动建议。
4. 只允许使用我提供的事实信息，不得编造政策条款、数字、案例或人物。
5. 严禁逐句改写或复述任何参考资料的原句，必须以自己的叙述重新组织。

输出格式（严格遵循）：
第一行：标题（原样输出我给你的标题，一个字都不要改）
空一行
正文（使用 Markdown 的 ## 作为小标题）"""


def _compliance_block():
    return (
        "【合规约束】\n"
        "- 以下参考资料只用于了解话题的**信息点与结构**，禁止照搬其句子、段落顺序与独特表达；\n"
        "- 成品必须是重新组织的叙述，且必须包含我给出的「公开信息」中的具体事实；\n"
        "- 不得编造任何数字、政策名称、时间或机构名称。\n"
    )


def build_prompt(title, topic, template=None, skeleton=None, hooks=None,
                  increments=None, keywords=None, word_count=1200):
    """组装改写 prompt（不含原文！只含结构 + 公开信息）"""
    parts = []

    parts.append("【任务】围绕话题「%s」写一篇公众号文章。" % topic)
    parts.append("标题已定，必须原样使用：\n%s" % title)
    parts.append("")

    if template:
        parts.append("【该方向的爆款规律（仅参考，不要照抄任何句子）】")
        if template.get("title_patterns"):
            parts.append("常见标题手法：" + "、".join(t for t, _ in template["title_patterns"]))
        if template.get("topic_types"):
            parts.append("常见选题类型：" + "、".join(t for t, _ in template["topic_types"]))
        if template.get("top_tags"):
            parts.append("高频关键词：" + "、".join(t for t, _ in template["top_tags"]))
        parts.append("")

    if skeleton:
        parts.append("【建议的正文骨架（只借用结构，内容自己写）】")
        for s in skeleton:
            pts = ("（要点可以是：" + "、".join(s.get("points", [])) + "）") if s.get("points") else ""
            parts.append("- %s：%s%s" % (s.get("role", ""), s.get("desc", ""), pts))
        parts.append("")

    if hooks:
        parts.append("【这篇标题的吸引力手法（写作时要在开头呼应）】")
        for h in hooks:
            parts.append("- " + h)
        parts.append("")

    if increments:
        parts.append("【公开信息 —— 必须用进去的具体事实】")
        for it in increments:
            t = it.get("title", "")
            sn = it.get("snippet", "")
            src = it.get("source", "")
            if t:
                parts.append("- %s%s%s" % (t, ("（%s）" % src) if src else "", ("：" + sn) if sn else ""))
        parts.append("")

    if keywords:
        parts.append("自然覆盖这些词：%s" % "、".join(keywords))
        parts.append("")

    parts.append("篇幅约 %d 字。" % word_count)
    parts.append("")
    parts.append(_compliance_block())
    return "\n".join(parts)


def call_llm(prompt, settings, timeout=120):
    """调用 OpenAI 兼容接口"""
    base = (settings.get("llm_base") or "").rstrip("/")
    key = settings.get("llm_key") or ""
    model = settings.get("llm_model") or "gpt-4o-mini"
    if not base or not key:
        raise RuntimeError("未配置 LLM API（base/key）")

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.75,
    }
    req = urllib.request.Request(
        base + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
        method="POST",
    )
    import ssl as _ssl
    ctx = _ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = _ssl.CERT_NONE
    resp = urllib.request.urlopen(req, timeout=timeout, context=ctx).read().decode("utf-8", "replace")
    d = json.loads(resp)
    if "choices" not in d:
        raise RuntimeError("接口返回异常：%s" % resp[:300])
    return d["choices"][0]["message"]["content"]


def split_title_body(text, fallback_title):
    """从模型输出里拆出标题与正文，并强制标题锁定"""
    lines = [l for l in (text or "").splitlines()]
    body_start = 0
    for i, l in enumerate(lines):
        if l.strip():
            body_start = i + 1
            break
    body = "\n".join(lines[body_start:]).strip()
    return fallback_title, body


def build_brief(title, topic, template, skeleton, hooks, increments, keywords, word_count):
    """未配置 LLM 时的产出：一份可直接照着写的任务书"""
    L = []
    L.append("## 写作任务书")
    L.append("")
    L.append("**话题**：%s" % topic)
    L.append("**标题（已锁定，不得改动）**：%s" % title)
    L.append("**目标篇幅**：约 %d 字" % word_count)
    L.append("")
    L.append("### 一、这篇要借用哪些爆款规律")
    if template:
        if template.get("title_patterns"):
            L.append("- 标题手法：%s" % "、".join(t for t, _ in template["title_patterns"]))
        if template.get("topic_types"):
            L.append("- 选题类型：%s" % "、".join(t for t, _ in template["topic_types"]))
        if template.get("top_tags"):
            L.append("- 高频词：%s" % "、".join(t for t, _ in template["top_tags"]))
    if hooks:
        L.append("- 开头要呼应的手法：")
        for h in hooks:
            L.append("  - %s" % h)
    L.append("")
    L.append("### 二、正文骨架（按此推进）")
    for i, s in enumerate(skeleton or [], 1):
        pts = ("，可涉及：" + "、".join(s.get("points", []))) if s.get("points") else ""
        L.append("%d. **%s** —— %s%s" % (i, s.get("role", ""), s.get("desc", ""), pts))
    L.append("")
    L.append("### 三、必须补进去的公开信息（这是区别于原文的关键）")
    if increments:
        for it in increments:
            if it.get("title"):
                L.append("- %s%s" % (it["title"], ("：" + it.get("snippet", "")[:160]) if it.get("snippet") else ""))
    else:
        L.append("- （未取到公开信息，建议先补一次增量抓取）")
    L.append("")
    L.append("### 四、写作纪律")
    L.append("- 标题一个字都不改。")
    L.append("- 只借用结构与选题角度，**不要逐句改写任何参考文章**。")
    L.append("- 每段用自己的话重新组织；不得编造政策、数字、机构、案例。")
    L.append("- 面向 50-70 岁读者：短句、口语、多分段。")
    L.append("- 结尾给一句实在提醒（如怎么查、去哪办、注意什么）。")
    return "\n".join(L)


def generate(article_id, topic=None, template=None, increments=None,
             word_count=1200, use_llm=True):
    """
    生成一篇草稿。
    返回 dict: {article_id, topic, title, body, outline, increments, engine}
    """
    art = db.get_article(article_id)
    if not art:
        raise ValueError("素材不存在: %s" % article_id)

    # 标题锁定
    title = art.get("title") or ""
    topic = topic or art.get("topic") or ""

    # 取结构（优先用已存分析）
    an = db.get_analysis(article_id) or analyzer.analyze_article(art)
    skeleton = an.get("skeleton", [])
    hooks = an.get("hooks", [])
    tags = an.get("tags", [])

    # 话题级模板
    if template is None:
        arts_t = db.list_articles(topic=topic, has_body=True, limit=200)
        ans = [x for x in (db.get_analysis(a["id"]) for a in arts_t) if x]
        template = analyzer.aggregate_template(arts_t, ans) if ans else {}

    # 增量
    if increments is None:
        increments = []

    prompt = build_prompt(title, topic, template, skeleton, hooks,
                          increments, tags, word_count)

    settings = db.get_settings()
    engine = "brief"
    body = ""

    if use_llm and settings.get("llm_key"):
        try:
            raw = call_llm(prompt, settings)
            _, body = split_title_body(raw, title)
            engine = "llm:%s" % settings.get("llm_model", "")
        except Exception as e:
            body = build_brief(title, topic, template, skeleton, hooks, increments, tags, word_count)
            body += "\n\n---\n> LLM 调用失败，已降级为任务书：%s" % e
            engine = "brief(llm_error)"

    if not body:
        body = build_brief(title, topic, template, skeleton, hooks, increments, tags, word_count)

    outline = json.dumps(skeleton, ensure_ascii=False)

    did = db.create_draft({
        "article_id": article_id,
        "topic": topic,
        "title": title,          # 锁定
        "body": body,
        "outline": outline,
        "increments": increments,
        "source_urls": [art.get("real_url") or ""],
        "engine": engine,
        "status": "draft",
    })
    return {
        "draft_id": did,
        "article_id": article_id,
        "topic": topic,
        "title": title,
        "body": body,
        "outline": skeleton,
        "increments": increments,
        "engine": engine,
        "prompt": prompt,
    }


if __name__ == "__main__":
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import fetcher

    arts = db.list_articles(has_body=True, limit=5)
    if not arts:
        print("没有可用素材（需先采集带正文的文章）")
        sys.exit(0)
    a = arts[0]
    print("素材：", a["title"])
    inc = fetcher.gather_increments(["养老金 上调"], 4)
    r = generate(a["id"], increments=inc, use_llm=False)
    print("引擎：", r["engine"])
    print("草稿ID：", r["draft_id"])
    print("-" * 50)
    print(r["body"][:1200])
