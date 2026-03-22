"""
科技马前卒 · 国际财经文章一键发布工具

输入一个话题 → Kimi 联网搜索最新新闻 → Kimi 生成文章 → 同时发布到：
  1. 微信公众号草稿箱
  2. GitHub Pages 个人网站（通过 GitHub API 自动提交）
  3. 钉钉群通知

运行方式：
  - GitHub Actions（提交 Issue / 手动触发）
  - 命令行: python gzh_news_writer.py gen "话题"
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import time
import urllib.parse
from datetime import datetime
from typing import Any, Dict, List, Optional
from datetime import datetime


import requests
from openai import OpenAI

# ==================== 日志 ====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("gzh")

# ==================== 配置（从环境变量读取） ====================

KIMI_API_KEY = os.getenv("KIMI_API_KEY", "")
KIMI_BASE_URL = os.getenv("KIMI_BASE_URL", "https://api.moonshot.cn/v1")
KIMI_MODEL = os.getenv("KIMI_MODEL", "kimi-k2.5")

WX_APPID = os.getenv("WX_APPID", "wxfb63a56ad8ccf4e9")
WX_APPSECRET = os.getenv("WX_APPSECRET", "f77cfbc5ce0daba5dd517eba43281d75")
WX_THUMB_MEDIA_ID = os.getenv("WX_THUMB_MEDIA_ID", "mvY2aVVddZ1IF8KCyZvchZA9K4dOCC3uELki_OfhWofmEYlgvM0Ywky831xZ3W2H")
WX_AUTHOR = os.getenv("WX_AUTHOR", "价值慢生活")

# 公众号2：科技马前卒
WX_APPID2 = os.getenv("WX_APPID2", "")
WX_APPSECRET2 = os.getenv("WX_APPSECRET2", "")
WX_THUMB_MEDIA_ID2 = os.getenv("WX_THUMB_MEDIA_ID2", "")
WX_AUTHOR2 = os.getenv("WX_AUTHOR2", "科技马前卒")

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "mumfordragg5-jpg/my_website")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")

DINGTALK_WEBHOOK = os.getenv("DINGTALK_WEBHOOK", "")
DINGTALK_SECRET = os.getenv("DINGTALK_SECRET", "")

today = datetime.now().strftime("%Y年%m月%d日")

TAG_RULES = [
    (["股市", "A股", "美股", "港股", "纳斯达克", "标普", "道琼斯", "stock", "market", "equity"], "市场"),
    (["地缘", "战争", "制裁", "军事", "导弹", "冲突", "中东", "俄乌", "geopolit", "war", "sanction"], "地缘"),
    (["中国", "中美", "人民币", "央行", "china", "beijing", "rmb"], "中国"),
    (["石油", "天然气", "能源", "OPEC", "oil", "gas", "energy"], "能源"),
    (["关税", "贸易", "tariff", "trade"], "热点"),
    (["美联储", "加息", "降息", "通胀", "fed", "inflation", "rate"], "热点"),
]

TAG_EMOJI = {"市场": "📊", "热点": "🔥", "中国": "🇨🇳", "地缘": "🌍", "能源": "⚡"}


# ==================== Kimi 联网生成文章 ====================

SYSTEM_PROMPT = (
    "你是一位资深财经自媒体作者，专注于解读国际财经新闻，面向中国读者撰写微信公众号文章。"
    "你的风格犀利、有深度、善用比喻，既专业又不枯燥。"
    "在写作前，请先使用联网搜索工具检索该话题的最新新闻动态，确保文章内容基于真实、最新的信息。"
)

# ARTICLE_PROMPT_TEMPLATE = """请先联网搜索「{topic}」的最新新闻（重点关注最近48小时内的报道），然后基于搜索结果撰写一篇公众号文章。
ARTICLE_PROMPT_TEMPLATE = """今天是{today}，请搜索「{topic}」最近7天内的最新新闻。

**重要：文章中引用的所有数据、日期、事件必须来自{today}前7天内的真实报道。如果搜索不到近期相关新闻，请如实说明，不要使用旧数据或编造数据。**

写作要求：

一、文章结构（严格按照以下顺序）：
1. 标题：中文，要有冲击力和悬念感，15-30字，可以用问号或感叹号，要让人忍不住点进来
2. 开头钩子：一句话点题，加粗，制造紧张感或颠覆认知
3. 发生了什么：用2-3段简明扼要说清核心事实，要有具体数据
4. 为什么重要：补充背景知识，让不了解的读者也能看懂
5. 深度分析：这是文章的核心，要有你自己的逻辑推理和独到见解，分2-3个小节展开，每节用"01 02 03"编号+小标题
6. 对中国的影响：读者最关心这个，要具体、接地气（影响股市？汇率？某个行业？普通人的钱包？）
7. 结尾：用一句精炼的金句收束全文，要有力量感，让人想转发

二、风格要求：
- 短句为主，一段不超过3-4行，适合手机阅读
- 重要观点用**加粗**标注
- 善用比喻和类比让复杂概念通俗化
- 语气自信但不傲慢，像一个见多识广的朋友在跟你聊天
- 每个小节开头用设问句引入，保持阅读节奏
- 不要用"让我们""首先""其次"这类教科书式的过渡词
- 信息来源要自然提及（如"据彭博社报道"），增加可信度

三、禁止事项：
- 不要直接翻译原文，要用自己的话重新组织
- 不要堆砌数据，每个数据都要解释它意味着什么
- 不要写空洞的套话，每句话都要有信息量
- 不要用"小编""宝宝们"等低质自媒体用语
- 不要在文中使用emoji表情符号

四、结尾固定格式：
用一条分割线后写上：
*关注我，带你看更多国际新闻。觉得有价值，点个「在看」，让更多人看到。*

文章字数：1500-2500字。

请直接输出文章内容，不要加任何额外说明。标题单独一行放在最前面。"""

def generate_article(topic: str) -> Dict[str, str]:
    client = OpenAI(api_key=KIMI_API_KEY, base_url=KIMI_BASE_URL)
    prompt = ARTICLE_PROMPT_TEMPLATE.format(topic=topic)

    log.info(f"Kimi 联网生成中: [{topic}]")
    t0 = time.time()

    resp = client.chat.completions.create(
        model=KIMI_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.6,
        max_tokens=4096,
        extra_body={"thinking": {"type": "disabled"}},
        tools=[{"type": "builtin_function", "function": {"name": "$web_search"}}],
        tool_choice="auto",
    )

    choice = resp.choices[0]
    log.info(f"第一轮 finish_reason={choice.finish_reason}, tool_calls={bool(choice.message.tool_calls)}")

    if choice.message.content:
        raw = choice.message.content.strip()
    else:
        tool_calls = choice.message.tool_calls or []
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        }
                    }
                    for tc in tool_calls
                ],
            },
        ]
        for tc in tool_calls:
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": tc.function.arguments,
            })

        log.info("第二轮生成文章...")
        resp2 = client.chat.completions.create(
            model=KIMI_MODEL,
            messages=messages,
            temperature=0.6,
            max_tokens=4096,
            extra_body={"thinking": {"type": "disabled"}},
        )
        raw = resp2.choices[0].message.content.strip()

    if not raw:
        raise RuntimeError("Kimi 未返回文章内容")

    log.info(f"Kimi 完成, 耗时 {time.time()-t0:.1f}s, 字数 {len(raw)}")

    lines = raw.split("\n")
    title, content_lines = "", []
    for line in lines:
        s = line.strip()
        if not title and s:
            title = s.lstrip("#").strip()
            continue
        content_lines.append(line)
    
    content = "\n".join(content_lines).strip()
    
    # 清洗开头的模型思考过程（遇到第一个空行+正文段落之前的废话）
    # 删掉正文第一个实质段落之前以"让我"、"由于"、"我将"开头的行
    cleaned_lines = []
    preamble_done = False
    for line in content.split("\n"):
        s = line.strip()
        if not preamble_done:
            if s and any(s.startswith(kw) for kw in ["让我", "由于", "我将", "我会", "根据搜索", "搜索结果"]):
                continue  # 跳过思考过程
            else:
                preamble_done = True
        cleaned_lines.append(line)
    
    return {"title": title, "content": "\n".join(cleaned_lines).strip()}

# ==================== 标签分类 ====================

def auto_tags(topic: str, title: str) -> List[str]:
    text = (topic + " " + title).lower()
    tags = []
    for keywords, tag in TAG_RULES:
        if any(kw.lower() in text for kw in keywords):
            if tag not in tags:
                tags.append(tag)
    return tags[:2] if tags else ["热点"]


# ==================== Markdown → 微信公众号 HTML ====================

def _inline_fmt(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"<b style='color:#c0392b;'>\1</b>", text)
    text = re.sub(r"\*(.+?)\*", r"<em style='color:#555;'>\1</em>", text)
    return text


def md_to_wx_html(md: str) -> str:
    parts, in_list, empty_count = [], False, 0
    for line in md.split("\n"):
        s = line.strip()
        if not s:
            if in_list:
                parts.append("</ul>")
                in_list = False
            empty_count += 1
            if empty_count > 1:
                continue
            continue
        else:
            empty_count = 0
        if s.startswith("---") or s.startswith("***"):
            if in_list:
                parts.append("</ul>")
                in_list = False
            parts.append("<hr style='border:none;border-top:1px solid #ddd;margin:20px 0;'/>")
            continue
        if s.startswith("- ") or s.startswith("• "):
            if not in_list:
                parts.append("<ul style='font-size:15px;line-height:1.8;padding-left:20px;'>")
                in_list = True
            parts.append(f"<li>{_inline_fmt(s[2:])}</li>")
            continue
        if in_list:
            parts.append("</ul>")
            in_list = False
        hm = re.match(r"^(#{1,3})\s+(.+)$", s)
        if hm:
            lv = len(hm.group(1))
            sz = {1: "20px", 2: "17px", 3: "16px"}.get(lv, "16px")
            parts.append(f"<h{lv} style='font-size:{sz};font-weight:bold;color:#333;margin:18px 0 10px;'>{_inline_fmt(hm.group(2))}</h{lv}>")
            continue
        nm = re.match(r"^(0[1-9]|[1-9]\d?)\s+(.+)$", s)
        if nm:
            parts.append(f"<h3 style='font-size:16px;font-weight:bold;color:#333;margin:18px 0 10px;'><span style='color:#c0392b;font-weight:bold;'>{nm.group(1)}</span> {_inline_fmt(nm.group(2))}</h3>")
            continue
        parts.append(f"<p style='font-size:15px;line-height:1.8;color:#333;margin:8px 0;text-align:justify;'>{_inline_fmt(s)}</p>")
    if in_list:
        parts.append("</ul>")
    return "\n".join(parts)


# ==================== Markdown → GitHub 网站文章 HTML ====================

def _inline_fmt_web(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    return text


def md_to_website_body(md: str) -> str:
    parts, in_list, in_bq = [], False, False
    for line in md.split("\n"):
        s = line.strip()
        if not s:
            if in_list:
                parts.append("</ul>")
                in_list = False
            if in_bq:
                parts.append("</blockquote>")
                in_bq = False
            continue
        if s.startswith("> "):
            if not in_bq:
                parts.append("<blockquote>")
                in_bq = True
            parts.append(f"<p>{_inline_fmt_web(s[2:])}</p>")
            continue
        if in_bq:
            parts.append("</blockquote>")
            in_bq = False
        if s.startswith("---") or s.startswith("***"):
            if in_list:
                parts.append("</ul>")
                in_list = False
            parts.append("<hr>")
            continue
        if s.startswith("- ") or s.startswith("• "):
            if not in_list:
                parts.append("<ul>")
                in_list = True
            parts.append(f"<li>{_inline_fmt_web(s[2:])}</li>")
            continue
        if in_list:
            parts.append("</ul>")
            in_list = False
        hm = re.match(r"^(#{1,3})\s+(.+)$", s)
        if hm:
            lv = len(hm.group(1)) + 1
            parts.append(f"<h{lv}>{_inline_fmt_web(hm.group(2))}</h{lv}>")
            continue
        nm = re.match(r"^(0[1-9]|[1-9]\d?)\s+(.+)$", s)
        if nm:
            parts.append(f"<h2>{nm.group(1)} {_inline_fmt_web(nm.group(2))}</h2>")
            continue
        parts.append(f"<p>{_inline_fmt_web(s)}</p>")
    if in_list:
        parts.append("</ul>")
    if in_bq:
        parts.append("</blockquote>")
    return "\n".join(parts)


def build_article_page_html(title: str, md_content: str, tags: List[str],
                            source: str, date_str: str) -> str:
    body_html = md_to_website_body(md_content)
    reading_min = max(5, len(md_content) // 400)
    tag_spans = "\n".join(
        f'                    <span class="card-tag">{TAG_EMOJI.get(t, "🔥")} {t}</span>'
        for t in tags
    )
    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} | 科技马前卒</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="../css/style.css">
</head>
<body>
    <div class="reading-progress" id="readingProgress"></div>
    <header class="site-header">
        <nav class="nav-inner">
            <a href="../index.html" class="site-logo"><span class="logo-icon">🏇</span> 科技马前卒</a>
            <div class="nav-right">
                <ul class="nav-links" id="navLinks">
                    <li><a href="../index.html">首页</a></li>
                    <li><a href="../index.html#articles" class="nav-active">文章</a></li>
                    <li><a href="../index.html#about">关于</a></li>
                </ul>
                <button class="theme-toggle" id="themeToggle">🌙</button>
                <button class="menu-toggle" id="menuToggle"><span></span><span></span><span></span></button>
            </div>
        </nav>
    </header>
    <div class="back-link"><a href="../index.html">← 返回首页</a></div>
    <article>
        <header class="article-header">
            <div class="card-tags-row">
{tag_spans}
            </div>
            <h1 class="article-title">{title}</h1>
            <div class="article-meta-line">
                <span>📅 {date_str}</span>
                <span>📖 约 {reading_min} 分钟阅读</span>
                <span>📰 来源: {source}</span>
            </div>
        </header>
        <div class="article-body">
            <div class="article-content">
{body_html}
            </div>
        </div>
    </article>
    <footer class="site-footer">
        <div class="footer-inner">
            <ul class="footer-links">
                <li><a href="../index.html">首页</a></li>
                <li><a href="../index.html#articles">文章</a></li>
                <li><a href="../index.html#about">关于</a></li>
            </ul>
            <p class="footer-copy">&copy; {datetime.now().year} 科技马前卒 · 帮中国人读懂西方财经头条</p>
        </div>
    </footer>
    <script src="../js/main.js"></script>
</body>
</html>'''


def build_index_card_html(slug: str, title: str, excerpt: str, tags: List[str],
                          source: str, date_str: str) -> str:
    tag_spans = "\n".join(
        f'                        <span class="card-tag{" tag-secondary" if i > 0 else ""}">{TAG_EMOJI.get(t, "🔥")} {t}</span>'
        for i, t in enumerate(tags)
    )
    tags_str = " ".join(tags)
    return f'''
            <div class="article-card fade-in" data-tags="{tags_str}" data-title="{title}" data-search="{title} {tags_str} {source}">
                <div class="card-body">
                    <div class="card-tags-row">
{tag_spans}
                    </div>
                    <h2 class="card-title">
                        <a href="articles/{slug}.html">{title}</a>
                    </h2>
                    <p class="card-excerpt">{excerpt}</p>
                    <div class="card-footer">
                        <div class="card-meta">
                            <span>{date_str}</span>
                            <span>约 8 分钟</span>
                        </div>
                        <span class="card-source">{source}</span>
                    </div>
                </div>
            </div>'''


# ==================== 微信公众号发布 ====================

def publish_wx_draft(title: str, html_content: str,
                     appid: str = None, appsecret: str = None,
                     thumb_media_id: str = None, author: str = None) -> Dict[str, Any]:
    appid = appid or WX_APPID
    appsecret = appsecret or WX_APPSECRET
    thumb_media_id = thumb_media_id or WX_THUMB_MEDIA_ID
    author = author or WX_AUTHOR
    r = requests.get("https://api.weixin.qq.com/cgi-bin/token", params={
        "grant_type": "client_credential", "appid": appid, "secret": appsecret,
    }, timeout=15)
    r.raise_for_status()
    token = r.json().get("access_token")
    if not token:
        raise RuntimeError(f"获取 access_token 失败: {r.json()}")

    payload = {"articles": [{
        "title": title, "content": html_content, "content_source_url": "",
        "thumb_media_id": thumb_media_id, "author": author,
        "digest": title[:60], "show_cover_pic": 0,
        "need_open_comment": 1, "only_fans_can_comment": 0,
    }]}
    r2 = requests.post(
        f"https://api.weixin.qq.com/cgi-bin/draft/add?access_token={token}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        timeout=30)
    r2.raise_for_status()
    return r2.json()


# ==================== GitHub API ====================

def _gh_headers() -> Dict[str, str]:
    return {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}


def _gh_get_file(path: str) -> Optional[Dict[str, Any]]:
    r = requests.get(
        f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}?ref={GITHUB_BRANCH}",
        headers=_gh_headers(), timeout=15)
    return r.json() if r.status_code == 200 else None


def _gh_put_file(path: str, content: str, message: str, sha: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        "branch": GITHUB_BRANCH,
    }
    if sha:
        payload["sha"] = sha
    r = requests.put(
        f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}",
        headers=_gh_headers(), data=json.dumps(payload), timeout=30)
    r.raise_for_status()
    return r.json()


def push_to_github(slug: str, article_html: str, article_md: str,
                   title: str, excerpt: str, tags: List[str],
                   source: str, date_str: str) -> Dict[str, str]:
    results = {}

    html_path = f"articles/{slug}.html"
    existing = _gh_get_file(html_path)
    _gh_put_file(html_path, article_html, f"Add article: {title}",
                 existing["sha"] if existing else None)
    results["article_html"] = html_path
    log.info(f"GitHub: {html_path}")

    md_path = f"articles/{slug}.md"
    existing_md = _gh_get_file(md_path)
    _gh_put_file(md_path, f"# {title}\n\n{article_md}", f"Add article md: {title}",
                 existing_md["sha"] if existing_md else None)
    results["article_md"] = md_path
    log.info(f"GitHub: {md_path}")

    index_info = _gh_get_file("index.html")
    if index_info:
        index_content = base64.b64decode(index_info["content"]).decode("utf-8")
        new_card = build_index_card_html(slug, title, excerpt, tags, source, date_str)

        marker = "<!-- ARTICLE_INSERT_MARKER -->"
        if marker in index_content:
            index_content = index_content.replace(marker, marker + "\n" + new_card)
        else:
            insert_point = '<div class="article-grid"'
            if insert_point in index_content:
                idx = index_content.find(">", index_content.find(insert_point))
                if idx != -1:
                    index_content = index_content[:idx+1] + "\n" + new_card + index_content[idx+1:]

        old_match = re.search(r'(\d+)\s*<br/>\s*篇深度文章', index_content)
        if old_match:
            old_count = int(old_match.group(1))
            index_content = index_content.replace(
                f"{old_count}\n", f"{old_count + 1}\n", 1
            ).replace(
                f"{old_count}<br/>", f"{old_count + 1}<br/>", 1
            )

        _gh_put_file("index.html", index_content, f"Update index: add {title}", index_info["sha"])
        results["index_updated"] = True
        log.info("GitHub: 首页已更新")

    return results


# ==================== 钉钉通知 ====================

def send_dingtalk(text: str):
    if not DINGTALK_WEBHOOK:
        return
    try:
        url = DINGTALK_WEBHOOK
        if DINGTALK_SECRET:
            ts = str(round(time.time() * 1000))
            sign_str = f"{ts}\n{DINGTALK_SECRET}"
            sign = urllib.parse.quote_plus(base64.b64encode(
                hmac.new(DINGTALK_SECRET.encode(), sign_str.encode(), hashlib.sha256).digest()
            ))
            url += f"&timestamp={ts}&sign={sign}"
        requests.post(url, json={"msgtype": "text", "text": {"content": text}}, timeout=10)
    except Exception as e:
        log.warning(f"钉钉通知失败: {e}")


# ==================== 主流程 ====================

def generate_slug(title: str) -> str:
    ts = datetime.now().strftime("%Y%m%d")
    clean = re.sub(r'[^\w\s-]', '', title)
    clean = re.sub(r'[\s]+', '-', clean).strip('-').lower()[:50]
    if not clean or not any(c.isalpha() for c in clean):
        clean = f"article-{ts}"
    return f"{clean}-{ts}"


def run_pipeline(topic: str, source_hint: str = "综合",
                 publish_wx: bool = True, publish_wx2: bool = False,
                 publish_gh: bool = True) -> Dict[str, Any]:
    log.info(f"{'='*50}")
    log.info(f"话题: {topic}")
    log.info(f"{'='*50}")
    result: Dict[str, Any] = {"topic": topic, "status": "processing"}

    # Kimi 联网搜索 + 生成文章，一步完成
    article = generate_article(topic)
    title = article["title"]
    content_md = article["content"]
    slug = generate_slug(title)
    tags = auto_tags(topic, title)
    date_str = datetime.now().strftime("%Y年%m月%d日")
    date_short = datetime.now().strftime("%Y-%m-%d")

    excerpt_lines = [l.strip() for l in content_md.split("\n")
                     if l.strip() and not l.strip().startswith("#") and not l.strip().startswith("---")]
    excerpt = ""
    for line in excerpt_lines:
        clean = re.sub(r'\*+', '', line).strip()
        if len(clean) > 20:
            excerpt = clean[:150]
            break

    result.update({
        "title": title, "slug": slug, "tags": tags,
        "content_md": content_md, "excerpt": excerpt,
        "source": source_hint, "date": date_short,
    })

    if publish_wx:
        try:
            wx_html = md_to_wx_html(content_md)
            wx_result = publish_wx_draft(title, wx_html)
            result["wx_result"] = wx_result
            log.info(f"微信公众号: media_id={wx_result.get('media_id', 'N/A')}")
        except Exception as e:
            log.error(f"微信公众号失败: {e}")
            result["wx_error"] = str(e)

    if publish_wx2 and WX_APPID2:
        try:
            wx_html = md_to_wx_html(content_md)
            wx_result2 = publish_wx_draft(title, wx_html,
                appid=WX_APPID2, appsecret=WX_APPSECRET2,
                thumb_media_id=WX_THUMB_MEDIA_ID2, author=WX_AUTHOR2)
            result["wx_result2"] = wx_result2
            log.info(f"公众号2: media_id={wx_result2.get('media_id', 'N/A')}")
        except Exception as e:
            log.error(f"公众号2失败: {e}")
            result["wx_error2"] = str(e)

    if publish_gh and GITHUB_TOKEN:
        try:
            page_html = build_article_page_html(title, content_md, tags, source_hint, date_str)
            gh_result = push_to_github(slug, page_html, content_md, title, excerpt, tags, source_hint, date_short)
            result["gh_result"] = gh_result
            result["gh_url"] = f"https://mumfordragg5-jpg.github.io/my_website/articles/{slug}.html"
        except Exception as e:
            log.error(f"GitHub 失败: {e}")
            result["gh_error"] = str(e)

    if DINGTALK_WEBHOOK:
        msg = f"文章已生成！\n标题: {title}\n话题: {topic}"
        if result.get("gh_url"):
            msg += f"\n网站: {result['gh_url']}"
        send_dingtalk(msg)

    result["status"] = "done"
    log.info(f"完成: {title}")
    return result


# ==================== 命令行入口 ====================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="科技马前卒 · 文章一键发布")
    sub = parser.add_subparsers(dest="command")

    gen_p = sub.add_parser("gen", help="生成并发布文章")
    gen_p.add_argument("topic", type=str, help="话题")
    gen_p.add_argument("--source", type=str, default="综合")
    gen_p.add_argument("--no-wx", action="store_true", help="不发布到公众号")
    gen_p.add_argument("--no-wx2", action="store_true", help="不发布到公众号2（科技马前卒）")
    gen_p.add_argument("--no-gh", action="store_true", help="不发布到 GitHub")
    gen_p.add_argument("--save", type=str, default="", help="保存 Markdown 到文件")

    args = parser.parse_args()

    if args.command == "gen":
        if not KIMI_API_KEY:
            print("错误：请设置环境变量 KIMI_API_KEY")
            exit(1)

        result = run_pipeline(
            topic=args.topic,
            source_hint=args.source,
            publish_wx=not args.no_wx,
            publish_wx2=not args.no_wx2,
            publish_gh=not args.no_gh,
        )
        print(f"\n标题: {result['title']}")
        if result.get("gh_url"):
            print(f"网站: {result['gh_url']}")
        if result.get("wx_result", {}).get("media_id"):
            print(f"公众号: {result['wx_result']['media_id']}")

        if args.save:
            with open(args.save, "w", encoding="utf-8") as f:
                f.write(f"# {result['title']}\n\n{result['content_md']}")
            print(f"已保存: {args.save}")
    else:
        parser.print_help()
