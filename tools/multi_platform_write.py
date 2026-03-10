"""
科技马前卒 · 国际财经文章一键发布工具

输入一个话题 → 自动抓取新闻 → DeepSeek 生成文章 → 同时发布到：
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
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any, Dict, List, Optional

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

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

WX_APPID = os.getenv("WX_APPID", "wxfb63a56ad8ccf4e9")
WX_APPSECRET = os.getenv("WX_APPSECRET", "f77cfbc5ce0daba5dd517eba43281d75")
WX_THUMB_MEDIA_ID = os.getenv("WX_THUMB_MEDIA_ID", "mvY2aVVddZ1IF8KCyZvchZA9K4dOCC3uELki_OfhWofmEYlgvM0Ywky831xZ3W2H")
WX_AUTHOR = os.getenv("WX_AUTHOR", "价值慢生活")


# 公众号2：科技马前卒
WX_APPID2 = os.getenv("WX_APPID2", "")
WX_APPSECRET2 = os.getenv("WX_APPSECRET2", "")
WX_THUMB_MEDIA_ID2 = os.getenv("WX_THUMB_MEDIA_ID2", "")
WX_AUTHOR2 = os.getenv("WX_AUTHOR2", "科技马前卒")

# 今日头条配置
TOUTIAO_APP_ID = os.getenv("TOUTIAO_APP_ID", "")
TOUTIAO_APP_SECRET = os.getenv("TOUTIAO_APP_SECRET", "")
TOUTIAO_ACCESS_TOKEN = os.getenv("TOUTIAO_ACCESS_TOKEN", "")  # 今日头条的 access_token 有效期较长

# 小红书配置
XIAOHONGSHU_ACCESS_TOKEN = os.getenv("XIAOHONGSHU_ACCESS_TOKEN", "")
XIAOHONGSHU_USER_ID = os.getenv("XIAOHONGSHU_USER_ID", "")

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "mumfordragg5-jpg/my_website")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")

DINGTALK_WEBHOOK = os.getenv("DINGTALK_WEBHOOK", "")
DINGTALK_SECRET = os.getenv("DINGTALK_SECRET", "")

NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "")

MEDIA_SOURCES = {
    "bloomberg": "彭博社", "wall street journal": "华尔街日报",
    "wsj": "华尔街日报", "new york times": "纽约时报",
    "nytimes": "纽约时报", "economist": "经济学人",
    "reuters": "路透社", "financial times": "金融时报",
    "ft": "金融时报", "cnbc": "CNBC", "bbc": "BBC",
}

TAG_RULES = [
    (["股市", "A股", "美股", "港股", "纳斯达克", "标普", "道琼斯", "stock", "market", "equity"], "市场"),
    (["地缘", "战争", "制裁", "军事", "导弹", "冲突", "中东", "俄乌", "geopolit", "war", "sanction"], "地缘"),
    (["中国", "中美", "人民币", "央行", "china", "beijing", "rmb"], "中国"),
    (["石油", "天然气", "能源", "OPEC", "oil", "gas", "energy"], "能源"),
    (["关税", "贸易", "tariff", "trade"], "热点"),
    (["美联储", "加息", "降息", "通胀", "fed", "inflation", "rate"], "热点"),
]

TAG_EMOJI = {"市场": "📊", "热点": "🔥", "中国": "🇨🇳", "地缘": "🌍", "能源": "⚡"}


# ==================== 新闻抓取 ====================

def _headers() -> Dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
    }


def fetch_google_news_rss(query: str, num: int = 10) -> List[Dict[str, str]]:
    try:
        r = requests.get("https://news.google.com/rss/search",
                         params={"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"},
                         headers=_headers(), timeout=20)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        results = []
        for item in root.findall(".//item")[:num]:
            desc = re.sub(r"<[^>]+>", "", item.findtext("description", "")).strip()
            results.append({
                "title": item.findtext("title", ""),
                "source": item.findtext("source", ""),
                "date": item.findtext("pubDate", ""),
                "link": item.findtext("link", ""),
                "summary": desc[:500],
            })
        return results
    except Exception as e:
        log.warning(f"Google News RSS: {e}")
        return []


def fetch_newsapi(query: str, num: int = 10) -> List[Dict[str, str]]:
    if not NEWSAPI_KEY:
        return []
    try:
        r = requests.get("https://newsapi.org/v2/everything", params={
            "q": query, "language": "en", "sortBy": "publishedAt",
            "pageSize": num, "apiKey": NEWSAPI_KEY,
        }, timeout=20)
        r.raise_for_status()
        return [{
            "title": a.get("title", ""),
            "source": a.get("source", {}).get("name", ""),
            "date": a.get("publishedAt", ""),
            "link": a.get("url", ""),
            "summary": (a.get("description") or "")[:500],
        } for a in r.json().get("articles", [])]
    except Exception as e:
        log.warning(f"NewsAPI: {e}")
        return []


def fetch_bing_news(query: str, num: int = 10) -> List[Dict[str, str]]:
    try:
        r = requests.get("https://www.bing.com/news/search",
                         params={"q": query, "format": "rss", "count": num},
                         headers=_headers(), timeout=20)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        results = []
        for item in root.findall(".//item")[:num]:
            desc = re.sub(r"<[^>]+>", "", item.findtext("description", "")).strip()
            results.append({
                "title": item.findtext("title", ""),
                "source": item.findtext("source", ""),
                "date": item.findtext("pubDate", ""),
                "link": item.findtext("link", ""),
                "summary": desc[:500],
            })
        return results
    except Exception as e:
        log.warning(f"Bing News: {e}")
        return []


def aggregate_news(topic: str, num: int = 15) -> List[Dict[str, str]]:
    log.info(f"新闻聚合: [{topic}]")
    all_news = []
    for name, fn in [("Google", fetch_google_news_rss), ("NewsAPI", fetch_newsapi), ("Bing", fetch_bing_news)]:
        batch = fn(topic, num)
        log.info(f"  {name}: {len(batch)} 条")
        all_news.extend(batch)
        time.sleep(0.3)

    seen = set()
    unique = []
    for item in all_news:
        key = item["title"].strip().lower()
        if key and key not in seen:
            seen.add(key)
            unique.append(item)
    log.info(f"  去重后: {len(unique)} 条")
    return unique


def identify_source(name: str) -> str:
    lower = name.lower()
    for key, cn in MEDIA_SOURCES.items():
        if key in lower:
            return cn
    return name


def format_news_for_prompt(news_list: List[Dict[str, str]], max_items: int = 12) -> str:
    lines = []
    for i, item in enumerate(news_list[:max_items], 1):
        src = identify_source(item.get("source", ""))
        line = f"{i}. [{src}] {item['title']}"
        if item.get("summary"):
            line += f"\n   摘要: {item['summary']}"
        lines.append(line)
    return "\n\n".join(lines)


# ==================== DeepSeek 文章生成 ====================

SYSTEM_PROMPT = "你是一位资深财经自媒体作者，专注于解读国际财经新闻，面向中国读者撰写微信公众号文章。你的风格犀利、有深度、善用比喻，既专业又不枯燥。"

ARTICLE_PROMPT_TEMPLATE = """请根据以下新闻素材，围绕「{topic}」这个话题，帮我写一篇公众号文章。

参考新闻素材：
{news_material}

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


def generate_article(topic: str, news_material: str) -> Dict[str, str]:
    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
    prompt = ARTICLE_PROMPT_TEMPLATE.format(topic=topic, news_material=news_material)

    log.info("DeepSeek 生成中...")
    t0 = time.time()
    resp = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.8,
        max_tokens=4096,
    )
    raw = resp.choices[0].message.content.strip()
    log.info(f"DeepSeek 完成, 耗时 {time.time()-t0:.1f}s, 字数 {len(raw)}")

    lines = raw.split("\n")
    title = ""
    content_lines = []
    for line in lines:
        s = line.strip()
        if not title and s:
            title = s.lstrip("#").strip()
            continue
        content_lines.append(line)
    return {"title": title, "content": "\n".join(content_lines).strip()}


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
    parts, in_list ,empty_count = [], False, 0
    for line in md.split("\n"):
        s = line.strip()
        if not s:
            if in_list:
                parts.append("</ul>")
                in_list = False
            # parts.append("<br/>")
            empty_count += 1
            # 只允许最多 1 个空行，忽略连续空行
            if empty_count > 1:
                continue
            continue
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


def md_to_toutiao(md: str) -> str:
    """
    将 Markdown 转换为今日头条支持的格式
    今日头条支持标准 Markdown，但需要做一些优化：
    - 保持标准 Markdown 语法
    - 优化图片、链接格式
    - 适配移动端阅读
    """
    lines = []
    for line in md.split("\n"):
        s = line.strip()
        
        # 保持空行
        if not s:
            lines.append("")
            continue
            
        # 分割线
        if s.startswith("---") or s.startswith("***"):
            lines.append("---")
            continue
            
        # 标题：保持原样
        if s.startswith("#"):
            lines.append(s)
            continue
            
        # 列表：保持原样
        if s.startswith("- ") or s.startswith("* ") or s.startswith("+ "):
            lines.append(s)
            continue
            
        # 数字编号段落（01 02 03）转为二级标题
        nm = re.match(r"^(0[1-9]|[1-9]\d?)\s+(.+)$", s)
        if nm:
            lines.append(f"## {nm.group(1)} {nm.group(2)}")
            continue
            
        # 普通段落
        lines.append(s)
    
    return "\n".join(lines)


def md_to_xiaohongshu(md: str, title: str) -> str:
    """
    将 Markdown 转换为小红书风格的文本
    小红书特点：
    - 使用 emoji 表情增加活力
    - 短句为主，适合手机阅读
    - 使用话题标签 #
    - 分段清晰，每段不超过 3-4 行
    - 重点内容用 emoji 标注
    """
    lines = []
    
    # 添加标题（小红书风格）
    lines.append(f"📌 {title}\n")
    lines.append("─" * 20 + "\n")
    
    paragraph_count = 0
    
    for line in md.split("\n"):
        s = line.strip()
        
        # 跳过空行（但保留段落间隔）
        if not s:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        
        # 跳过分割线
        if s.startswith("---") or s.startswith("***"):
            lines.append("·" * 15)
            continue
        
        # 一级标题转为 emoji 标题
        if s.startswith("# "):
            title_text = s[2:].strip()
            lines.append(f"\n💡 {title_text}\n")
            continue
        
        # 二级标题转为 emoji 小标题
        if s.startswith("## "):
            title_text = s[3:].strip()
            lines.append(f"\n✨ {title_text}\n")
            continue
        
        # 三级标题
        if s.startswith("### "):
            title_text = s[4:].strip()
            lines.append(f"\n🔸 {title_text}\n")
            continue
        
        # 数字编号段落（01 02 03）
        nm = re.match(r"^(0[1-9]|[1-9]\d?)\s+(.+)$", s)
        if nm:
            lines.append(f"\n{nm.group(1)}️⃣ {nm.group(2)}\n")
            continue
        
        # 列表项转为 emoji 列表
        if s.startswith("- ") or s.startswith("* ") or s.startswith("+ "):
            item_text = s[2:].strip()
            lines.append(f"▫️ {item_text}")
            continue
        
        # 处理加粗文本（**text** 转为 emoji 强调）
        s = re.sub(r'\*\*(.+?)\*\*', r'【\1】', s)
        
        # 普通段落
        lines.append(s)
        paragraph_count += 1
    
    # 添加结尾引导
    lines.append("\n" + "─" * 20)
    lines.append("\n💬 你怎么看？欢迎评论区讨论")
    lines.append("❤️ 觉得有用记得点赞收藏哦")
    lines.append("\n#财经 #国际新闻 #深度解读")
    
    return "\n".join(lines)


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
    reading_min = max(5, 8)
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
                            <span>约 {reading_min} 分钟</span>
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


# ==================== 今日头条发布 ====================

def publish_toutiao_article(title: str, content: str, 
                            cover_images: List[str] = None) -> Dict[str, Any]:
    """
    发布文章到今日头条
    
    参数:
        title: 文章标题
        content: 文章内容（Markdown 格式）
        cover_images: 封面图片 URL 列表（可选，最多3张）
    
    返回:
        今日头条 API 响应
    
    注意：
        1. 需要先在今日头条开放平台申请账号并获取 access_token
        2. access_token 获取方式：https://open.toutiao.com/
        3. 文章会进入草稿箱，需要手动审核发布
    """
    if not TOUTIAO_ACCESS_TOKEN:
        raise RuntimeError("未配置今日头条 access_token，请设置环境变量 TOUTIAO_ACCESS_TOKEN")
    
    # 今日头条文章发布 API
    url = "https://open.toutiao.com/api/media/article/create/"
    
    # 构建请求参数
    payload = {
        "access_token": TOUTIAO_ACCESS_TOKEN,
        "title": title,
        "content": content,
        "content_type": "markdown",  # 使用 Markdown 格式
        "article_type": 0,  # 0-普通图文
        "save_draft": 1,  # 1-保存为草稿，0-直接发布
    }
    
    # 添加封面图（可选）
    if cover_images:
        payload["cover_images"] = cover_images[:3]  # 最多3张
    
    try:
        r = requests.post(url, json=payload, timeout=30)
        r.raise_for_status()
        result = r.json()
        
        if result.get("errcode") == 0:
            log.info(f"今日头条: 文章已保存到草稿箱, article_id={result.get('data', {}).get('article_id', 'N/A')}")
            return result
        else:
            raise RuntimeError(f"今日头条 API 错误: {result.get('errmsg', '未知错误')}")
            
    except Exception as e:
        log.error(f"今日头条发布失败: {e}")
        raise


def publish_toutiao_article(title: str, content: str, 
                            cover_images: List[str] = None) -> Dict[str, Any]:
    """
    发布文章到今日头条
    
    参数:
        title: 文章标题
        content: 文章内容（Markdown 格式）
        cover_images: 封面图片 URL 列表（可选，最多3张）
    
    返回:
        今日头条 API 响应
    
    注意：
        1. 需要先在今日头条开放平台申请账号并获取 access_token
        2. access_token 获取方式：https://open.toutiao.com/
        3. 文章会进入草稿箱，需要手动审核发布
    """
    if not TOUTIAO_ACCESS_TOKEN:
        raise RuntimeError("未配置今日头条 access_token，请设置环境变量 TOUTIAO_ACCESS_TOKEN")
    
    # 今日头条文章发布 API
    url = "https://open.toutiao.com/api/media/article/create/"
    
    # 构建请求参数
    payload = {
        "access_token": TOUTIAO_ACCESS_TOKEN,
        "title": title,
        "content": content,
        "content_type": "markdown",  # 使用 Markdown 格式
        "article_type": 0,  # 0-普通图文
        "save_draft": 1,  # 1-保存为草稿，0-直接发布
    }
    
    # 添加封面图（可选）
    if cover_images:
        payload["cover_images"] = cover_images[:3]  # 最多3张
    
    try:
        r = requests.post(url, json=payload, timeout=30)
        r.raise_for_status()
        result = r.json()
        
        if result.get("errcode") == 0:
            log.info(f"今日头条: 文章已保存到草稿箱, article_id={result.get('data', {}).get('article_id', 'N/A')}")
            return result
        else:
            raise RuntimeError(f"今日头条 API 错误: {result.get('errmsg', '未知错误')}")
            
    except Exception as e:
        log.error(f"今日头条发布失败: {e}")
        raise


def publish_xiaohongshu_note(title: str, content: str, 
                             images: List[str] = None,
                             topics: List[str] = None) -> Dict[str, Any]:
    """
    发布笔记到小红书
    
    参数:
        title: 笔记标题
        content: 笔记内容（纯文本，已转换为小红书风格）
        images: 图片 URL 列表（可选，最多9张）
        topics: 话题标签列表（可选）
    
    返回:
        小红书 API 响应
    
    注意：
        1. 需要先在小红书开放平台申请账号并获取 access_token
        2. 小红书 API 文档：https://open.xiaohongshu.com/
        3. 笔记会进入草稿箱，需要手动审核发布
        4. 小红书对内容审核较严格，建议人工审核后再发布
    """
    if not XIAOHONGSHU_ACCESS_TOKEN:
        raise RuntimeError("未配置小红书 access_token，请设置环境变量 XIAOHONGSHU_ACCESS_TOKEN")
    
    # 小红书笔记发布 API（注意：实际 API 地址可能需要根据官方文档调整）
    url = "https://edith.xiaohongshu.com/api/sns/web/v1/note/create"
    
    # 构建请求头
    headers = {
        "Authorization": f"Bearer {XIAOHONGSHU_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    
    # 构建请求参数
    payload = {
        "title": title[:20],  # 小红书标题限制20字
        "desc": content[:1000],  # 小红书正文限制1000字
        "type": "normal",  # 笔记类型：normal-普通笔记
        "post_time": "0",  # 0-立即发布，或指定时间戳
        "is_private": False,  # 是否私密
    }
    
    # 添加图片（可选）
    if images:
        payload["image_list"] = [{"url": img} for img in images[:9]]  # 最多9张
    
    # 添加话题标签（可选）
    if topics:
        payload["topics"] = [{"name": topic} for topic in topics[:10]]  # 最多10个话题
    
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=30)
        r.raise_for_status()
        result = r.json()
        
        if result.get("success") or result.get("code") == 0:
            note_id = result.get("data", {}).get("note_id", "N/A")
            log.info(f"小红书: 笔记已保存到草稿箱, note_id={note_id}")
            return result
        else:
            raise RuntimeError(f"小红书 API 错误: {result.get('msg', '未知错误')}")
            
    except Exception as e:
        log.error(f"小红书发布失败: {e}")
        raise


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
                 publish_gh: bool = True, publish_toutiao: bool = False,
                 publish_xiaohongshu: bool = False) -> Dict[str, Any]:
    log.info(f"{'='*50}")
    log.info(f"话题: {topic}")
    log.info(f"{'='*50}")
    result: Dict[str, Any] = {"topic": topic, "status": "processing"}

    news_list = aggregate_news(topic)
    if news_list:
        news_material = format_news_for_prompt(news_list)
        top_source = identify_source(news_list[0].get("source", ""))
        if top_source != news_list[0].get("source", ""):
            source_hint = top_source
    else:
        news_material = f"话题：{topic}\n（未找到具体新闻报道，请基于你的知识储备撰写）"

    article = generate_article(topic, news_material)
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

    if publish_toutiao and TOUTIAO_ACCESS_TOKEN:
        try:
            toutiao_content = md_to_toutiao(content_md)
            toutiao_result = publish_toutiao_article(title, toutiao_content)
            result["toutiao_result"] = toutiao_result
            article_id = toutiao_result.get("data", {}).get("article_id", "N/A")
            log.info(f"今日头条: article_id={article_id}")
        except Exception as e:
            log.error(f"今日头条失败: {e}")
            result["toutiao_error"] = str(e)

    if publish_xiaohongshu and XIAOHONGSHU_ACCESS_TOKEN:
        try:
            xhs_content = md_to_xiaohongshu(content_md, title)
            xhs_topics = [f"#{tag}" for tag in tags] + ["#财经", "#国际新闻"]
            xhs_result = publish_xiaohongshu_note(title, xhs_content, topics=xhs_topics)
            result["xiaohongshu_result"] = xhs_result
            note_id = xhs_result.get("data", {}).get("note_id", "N/A")
            log.info(f"小红书: note_id={note_id}")
        except Exception as e:
            log.error(f"小红书发布失败: {e}")
            result["xiaohongshu_error"] = str(e)

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
        if result.get("toutiao_result"):
            msg += f"\n今日头条: 已保存到草稿箱"
        if result.get("xiaohongshu_result"):
            msg += f"\n小红书: 已保存到草稿箱"
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
    gen_p.add_argument("--toutiao", action="store_true", help="发布到今日头条")
    gen_p.add_argument("--xiaohongshu", action="store_true", help="发布到小红书")
    gen_p.add_argument("--save", type=str, default="", help="保存 Markdown 到文件")

    args = parser.parse_args()

    if args.command == "gen":
        if not DEEPSEEK_API_KEY:
            print("错误：请设置环境变量 DEEPSEEK_API_KEY")
            exit(1)

        result = run_pipeline(
            topic=args.topic,
            source_hint=args.source,
            publish_wx=not args.no_wx,
            publish_wx2=not args.no_wx2,
            publish_gh=not args.no_gh,
            publish_toutiao=args.toutiao,
            publish_xiaohongshu=args.xiaohongshu,
        )
        print(f"\n标题: {result['title']}")
        if result.get("gh_url"):
            print(f"网站: {result['gh_url']}")
        if result.get("wx_result", {}).get("media_id"):
            print(f"公众号: {result['wx_result']['media_id']}")
        if result.get("toutiao_result"):
            article_id = result['toutiao_result'].get('data', {}).get('article_id', 'N/A')
            print(f"今日头条: {article_id}")
        if result.get("xiaohongshu_result"):
            note_id = result['xiaohongshu_result'].get('data', {}).get('note_id', 'N/A')
            print(f"小红书: {note_id}")

        if args.save:
            with open(args.save, "w", encoding="utf-8") as f:
                f.write(f"# {result['title']}\n\n{result['content_md']}")
            print(f"已保存: {args.save}")
    else:
        parser.print_help()


