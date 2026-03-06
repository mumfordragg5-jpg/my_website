"""
科技马前卒 - 全功能单文件版

集成所有功能：
  1. 新闻聚合（Google News RSS / NewsAPI / Bing News）
  2. DeepSeek API 文章生成（话题模式 + 标题模式）
  3. Markdown -> 微信公众号 HTML 转换
  4. 微信公众号草稿箱发布
  5. GitHub Pages 网站自动发布
  6. Flask Web 管理后台
  7. 钉钉机器人 Webhook

启动方式：
  python all_in_one.py                    # 启动 Web 后台
  python all_in_one.py --cli "美联储加息"   # 命令行话题模式
  python all_in_one.py --cli --headline "Fed Raises Rates" --source bloomberg

依赖安装：
  pip install openai flask markdown requests
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import time
import traceback
import xml.etree.ElementTree as ET
from datetime import datetime, date
from typing import Any, Dict, List

import requests
from openai import OpenAI

# ====================================================================
#                           配置区
#  只需要改这里的密钥，其他代码不用动
# ====================================================================

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "your-deepseek-api-key")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

WX_APPID = os.getenv("WX_APPID", "111")
WX_APPSECRET = os.getenv("WX_APPSECRET", "222")
WX_THUMB_MEDIA_ID = os.getenv("WX_THUMB_MEDIA_ID", "mvY2aVVddZ1IF8KCyZvchZA9K4dOCC3uELki_OfhWofmEYlgvM0Ywky831xZ3W2H")
WX_AUTHOR = os.getenv("WX_AUTHOR", "科技马前卒")

NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "")

DINGTALK_SECRET = os.getenv("DINGTALK_SECRET", "")

# 网站仓库本地路径（留空则不自动发布网站）
GITHUB_REPO_PATH = os.getenv("GITHUB_REPO_PATH", "")
GITHUB_AUTO_PUSH = os.getenv("GITHUB_AUTO_PUSH", "true").lower() == "true"

FLASK_PORT = int(os.getenv("FLASK_PORT", "5000"))

MEDIA_SOURCES = {
    "bloomberg": "彭博社", "wall street journal": "华尔街日报", "wsj": "华尔街日报",
    "new york times": "纽约时报", "nytimes": "纽约时报", "economist": "经济学人",
    "reuters": "路透社", "financial times": "金融时报", "ft": "金融时报",
    "cnbc": "CNBC", "bbc": "BBC",
}

SOURCE_SHORT_MAP = {
    "Bloomberg": "Bloomberg", "彭博社": "Bloomberg",
    "Wall Street Journal": "WSJ", "华尔街日报": "WSJ",
    "New York Times": "NYT", "纽约时报": "NYT",
    "The Economist": "Economist", "经济学人": "Economist",
    "Reuters": "Reuters", "路透社": "Reuters",
    "Financial Times": "FT", "金融时报": "FT",
}

TAG_MAP = {
    "市场": ("market", "📊 市场"), "热点": ("hotspot", "🔥 热点"),
    "中国": ("china", "🇨🇳 中国"), "地缘": ("geopolitics", "🌍 地缘"),
    "能源": ("energy", "⚡ 能源"), "科技": ("tech", "💻 科技"),
}


# ====================================================================
#                     1. 新闻聚合模块
# ====================================================================

def _http_headers() -> Dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
    }


def fetch_google_news_rss(query: str, num: int = 10) -> List[Dict[str, str]]:
    url = "https://news.google.com/rss/search"
    params = {"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"}
    try:
        r = requests.get(url, params=params, headers=_http_headers(), timeout=20)
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
        print(f"[Google News] 失败: {e}")
        return []


def fetch_newsapi(query: str, num: int = 10) -> List[Dict[str, str]]:
    if not NEWSAPI_KEY:
        return []
    url = "https://newsapi.org/v2/everything"
    params = {"q": query, "language": "en", "sortBy": "publishedAt", "pageSize": num, "apiKey": NEWSAPI_KEY}
    try:
        r = requests.get(url, params=params, timeout=20)
        r.raise_for_status()
        return [{
            "title": a.get("title", ""),
            "source": a.get("source", {}).get("name", ""),
            "date": a.get("publishedAt", ""),
            "link": a.get("url", ""),
            "summary": (a.get("description") or "")[:500],
        } for a in r.json().get("articles", [])]
    except Exception as e:
        print(f"[NewsAPI] 失败: {e}")
        return []


def fetch_bing_news(query: str, num: int = 10) -> List[Dict[str, str]]:
    url = "https://www.bing.com/news/search"
    params = {"q": query, "format": "rss", "count": num}
    try:
        r = requests.get(url, params=params, headers=_http_headers(), timeout=20)
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
        print(f"[Bing News] 失败: {e}")
        return []


def aggregate_news(topic: str, num: int = 15) -> List[Dict[str, str]]:
    all_news = []
    print(f"[新闻聚合] 搜索: {topic}")

    for name, fetcher in [("Google", fetch_google_news_rss), ("NewsAPI", fetch_newsapi), ("Bing", fetch_bing_news)]:
        results = fetcher(topic, num)
        if results:
            print(f"  - {name}: {len(results)} 条")
            all_news.extend(results)
            time.sleep(0.3)

    seen = set()
    unique = []
    for item in all_news:
        key = item["title"].strip().lower()
        if key and key not in seen:
            seen.add(key)
            unique.append(item)

    print(f"[新闻聚合] 去重后 {len(unique)} 条\n")
    return unique


def identify_source(source_name: str) -> str:
    lower = source_name.lower()
    for key, cn in MEDIA_SOURCES.items():
        if key in lower:
            return cn
    return source_name


def format_news_for_prompt(news_list: List[Dict[str, str]], max_items: int = 12) -> str:
    lines = []
    for i, item in enumerate(news_list[:max_items], 1):
        src = identify_source(item.get("source", ""))
        line = f"{i}. [{src}] {item['title']}"
        if item.get("summary"):
            line += f"\n   摘要: {item['summary']}"
        lines.append(line)
    return "\n\n".join(lines)


# ====================================================================
#                     2. DeepSeek 文章生成
# ====================================================================

SYSTEM_PROMPT = """你是一位资深财经自媒体作者，笔名"科技马前卒"，专注于解读国际财经新闻，面向中国读者撰写微信公众号文章。你的风格犀利、有深度、善用比喻，既专业又不枯燥。"""

WRITING_RULES = """
一、文章结构（严格按照以下顺序）：
1. 标题：中文，15-30字，有冲击力和悬念感
2. 开头钩子：一句话点题，加粗，制造紧张感或颠覆认知
3. 发生了什么：2-3段简明扼要说清核心事实，要有具体数据
4. 为什么重要：补充背景知识，让不了解的读者也能看懂
5. 深度分析：文章核心，有逻辑推理和独到见解，分2-3个小节，用"01 02 03"编号+小标题
6. 对中国的影响：要具体接地气（影响股市？汇率？哪个行业？普通人的钱包？）
7. 结尾：一句精炼金句收束全文，有力量感，让人想转发

二、风格要求：
- 短句为主，一段不超过3-4行，适合手机阅读
- 重要观点用**加粗**标注
- 善用比喻和类比让复杂概念通俗化
- 语气自信但不傲慢，像一个见多识广的朋友在跟你聊天
- 每个小节开头用设问句引入，保持阅读节奏
- 不要用"让我们""首先""其次"等教科书过渡词
- 信息来源要自然提及（如"据彭博社报道"），增加可信度

三、禁止事项：
- 不要直接翻译原文，用自己的话重新组织
- 不要堆砌数据，每个数据都要解释意味着什么
- 不要写空洞套话，每句话都要有信息量
- 不要用"小编""宝宝们"等低质自媒体用语
- 不要在文中使用emoji

四、结尾固定：分割线后写 *关注「科技马前卒」，了解更多国际新闻。觉得有价值，点个「在看」，让更多人看到。*

字数：1800-2800字。标题单独一行放最前面，不要加额外说明。"""


def generate_by_topic(topic: str) -> Dict:
    """话题模式：自动抓新闻 + 生成"""
    news_list = aggregate_news(topic)
    if not news_list:
        material = f"话题：{topic}\n（未找到具体新闻，请基于知识储备撰写）"
    else:
        material = format_news_for_prompt(news_list)
    prompt = f"请根据以下新闻素材，围绕「{topic}」这个话题，写一篇公众号文章。\n\n参考新闻素材：\n{material}\n\n写作要求：{WRITING_RULES}"
    result = _call_deepseek(prompt)
    result["news_sources"] = news_list
    return result


def generate_by_headline(headline: str, source: str = "国际媒体", extra_info: str = "") -> Dict:
    """标题模式：直接给标题生成"""
    prompt = f"请根据以下新闻信息，写一篇公众号文章。\n\n新闻标题：{headline}\n信息来源：{source}\n补充信息：{extra_info or '无'}\n\n写作要求：{WRITING_RULES}"
    result = _call_deepseek(prompt)
    result["source"] = source
    return result


def _call_deepseek(user_prompt: str) -> Dict:
    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
    print("[DeepSeek] 生成中...")
    start = time.time()

    resp = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.7,
        max_tokens=4096,
    )

    raw = resp.choices[0].message.content.strip()
    elapsed = time.time() - start
    print(f"[DeepSeek] 完成，耗时 {elapsed:.1f}s，字数 {len(raw)}\n")

    lines = raw.split("\n")
    title = ""
    content_lines = []
    for line in lines:
        s = line.strip()
        if not title and s:
            title = s.lstrip("#").strip()
            continue
        content_lines.append(line)

    return {"title": title, "content": "\n".join(content_lines).strip(), "content_full": raw}


# ====================================================================
#                  3. Markdown -> 微信公众号 HTML
# ====================================================================

def markdown_to_wx_html(md_text: str) -> str:
    lines = md_text.split("\n")
    html_parts = []
    in_list = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            html_parts.append("<br/>")
            continue

        if stripped.startswith("---") or stripped.startswith("***") or stripped.startswith("___"):
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            html_parts.append("<hr style='border:none; border-top:1px solid #ddd; margin:20px 0;'/>")
            continue

        if stripped.startswith("- ") or stripped.startswith("• "):
            if not in_list:
                html_parts.append("<ul style='font-size:15px; line-height:1.8; padding-left:20px;'>")
                in_list = True
            html_parts.append(f"<li>{_inline_fmt(stripped[2:])}</li>")
            continue

        if in_list:
            html_parts.append("</ul>")
            in_list = False

        hm = re.match(r"^(#{1,3})\s+(.+)$", stripped)
        if hm:
            lv = len(hm.group(1))
            sz = {1: "20px", 2: "17px", 3: "16px"}.get(lv, "16px")
            html_parts.append(f"<h{lv} style='font-size:{sz}; font-weight:bold; color:#333; margin:18px 0 10px 0;'>{_inline_fmt(hm.group(2))}</h{lv}>")
            continue

        nm = re.match(r"^(0[1-9]|[1-9]\d?)\s+(.+)$", stripped)
        if nm:
            html_parts.append(f"<h3 style='font-size:16px; font-weight:bold; color:#333; margin:18px 0 10px 0;'><span style='color:#c0392b; font-weight:bold;'>{nm.group(1)}</span> {_inline_fmt(nm.group(2))}</h3>")
            continue

        html_parts.append(f"<p style='font-size:15px; line-height:1.8; color:#333; margin:8px 0; text-align:justify;'>{_inline_fmt(stripped)}</p>")

    if in_list:
        html_parts.append("</ul>")
    return "\n".join(html_parts)


def _inline_fmt(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"<b style='color:#c0392b;'>\1</b>", text)
    text = re.sub(r"\*(.+?)\*", r"<em style='color:#555;'>\1</em>", text)
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    return text


# ====================================================================
#                   4. 微信公众号发布
# ====================================================================

def get_wx_access_token() -> str:
    url = "https://api.weixin.qq.com/cgi-bin/token"
    params = {"grant_type": "client_credential", "appid": WX_APPID, "secret": WX_APPSECRET}
    r = requests.get(url, params=params, timeout=15)
    data = r.json()
    if "access_token" not in data:
        raise RuntimeError(f"获取 access_token 失败: {data}")
    return data["access_token"]


def publish_to_wechat(title: str, md_content: str) -> Dict[str, Any]:
    """发布到微信公众号草稿箱"""
    html = markdown_to_wx_html(md_content)
    token = get_wx_access_token()
    url = f"https://api.weixin.qq.com/cgi-bin/draft/add?access_token={token}"
    payload = {"articles": [{
        "title": title, "content": html, "content_source_url": "",
        "thumb_media_id": WX_THUMB_MEDIA_ID, "author": WX_AUTHOR,
        "digest": title[:60], "show_cover_pic": 0,
        "need_open_comment": 1, "only_fans_can_comment": 0,
    }]}
    r = requests.post(url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                       headers={"Content-Type": "application/json; charset=utf-8"}, timeout=30)
    result = r.json()
    mid = result.get("media_id")
    print(f"[微信] {'成功 media_id=' + mid if mid else '异常: ' + str(result)}")
    return result


# ====================================================================
#                   5. GitHub Pages 网站发布
# ====================================================================

def publish_to_website(article: Dict, tags: List[str] = None) -> str:
    """生成 HTML 并推送到 GitHub Pages"""
    if not GITHUB_REPO_PATH:
        return ""

    tags = tags or ["热点"]
    date_str = date.today().strftime("%Y-%m-%d")
    slug = re.sub(r'[^\w\u4e00-\u9fff-]', '', article["title"].replace(" ", "-"))[:40]
    filename = f"{slug}.html"
    src_short = _get_source_short(article.get("source", ""))

    tag_html = ""
    for t in tags:
        if t in TAG_MAP:
            tag_html += f'    <span class="card-tag">{TAG_MAP[t][1]}</span>\n'

    import markdown as md_lib
    body_html = md_lib.markdown(article.get("content", ""), extensions=["extra"])

    page_html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{article["title"]} | 科技马前卒</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="../css/style.css">
  <link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>🏇</text></svg>">
</head>
<body>
  <div class="reading-progress" id="readingProgress"></div>
  <header class="site-header"><nav class="nav-inner">
    <a href="../index.html" class="site-logo"><span class="logo-icon">🏇</span>科技马前卒</a>
    <div class="nav-right">
      <ul class="nav-links" id="navLinks"><li><a href="../index.html">首页</a></li><li><a href="../index.html#articles">文章</a></li><li><a href="../index.html#about">关于</a></li></ul>
      <button class="theme-toggle" id="themeToggle" aria-label="切换主题">🌙</button>
      <button class="menu-toggle" id="menuToggle" aria-label="菜单"><span></span><span></span><span></span></button>
    </div>
  </nav></header>
  <div class="back-link"><a href="../index.html">← 返回首页</a></div>
  <header class="article-header">
{tag_html}    <h1 class="article-title">{article["title"]}</h1>
    <div class="article-meta-line"><span>📅 {date_str}</span><span>📖 约 8 分钟</span><span>📰 {src_short}</span></div>
  </header>
  <div class="article-body"><div class="article-content">{body_html}</div></div>
  <footer class="site-footer"><div class="footer-inner">
    <p>&copy; 2026 科技马前卒 · 帮中国人读懂西方财经头条</p>
  </div></footer>
  <script src="../js/main.js"></script>
</body>
</html>"""

    path = os.path.join(GITHUB_REPO_PATH, "articles", filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(page_html)

    _update_index_html(article, tags, date_str, filename, src_short)

    if GITHUB_AUTO_PUSH:
        try:
            subprocess.run(["git", "add", "-A"], cwd=GITHUB_REPO_PATH, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", f"Publish: {article['title'][:50]}"],
                           cwd=GITHUB_REPO_PATH, check=True, capture_output=True)
            subprocess.run(["git", "push"], cwd=GITHUB_REPO_PATH, check=True, capture_output=True)
            print(f"[网站] 发布成功: articles/{filename}")
        except subprocess.CalledProcessError as e:
            print(f"[网站] Git 推送失败: {e.stderr.decode() if e.stderr else e}")

    return f"articles/{filename}"


def _update_index_html(article, tags, date_str, filename, src_short):
    index_path = os.path.join(GITHUB_REPO_PATH, "index.html")
    if not os.path.exists(index_path):
        return
    with open(index_path, "r", encoding="utf-8") as f:
        html = f.read()

    tag_keys = ",".join(TAG_MAP[t][0] for t in tags if t in TAG_MAP)
    tag_badges = "".join(
        f'          <span class="card-tag{" tag-secondary" if i > 0 else ""}">{TAG_MAP[t][1]}</span>\n'
        for i, t in enumerate(tags) if t in TAG_MAP
    )
    excerpt = re.sub(r'[#*\n]', ' ', article.get("content", ""))[:100] + "..."

    card = f"""
    <article class="article-card fade-in" data-tags="{tag_keys}" data-title="{article['title']}" data-search="{article['title']}">
      <div class="card-body">
        <div class="card-tags-row">
{tag_badges}        </div>
        <h2 class="card-title"><a href="articles/{filename}">{article["title"]}</a></h2>
        <p class="card-excerpt">{excerpt}</p>
        <div class="card-footer">
          <div class="card-meta"><span>{date_str}</span><span>约 8 分钟</span></div>
          <span class="card-source">{src_short}</span>
        </div>
      </div>
    </article>
"""
    marker = '<div class="article-grid" id="articleGrid">'
    if marker in html:
        html = html.replace(marker, marker + card, 1)
        count = html.count('class="article-card')
        html = re.sub(r'(<span class="stat-number" id="articleCount">)\d+(</span>)', f"\\g<1>{count}\\2", html)
        with open(index_path, "w", encoding="utf-8") as f:
            f.write(html)


def _get_source_short(source: str) -> str:
    for k, v in SOURCE_SHORT_MAP.items():
        if k in source:
            return v
    return "Media"


# ====================================================================
#                    6. 钉钉机器人
# ====================================================================

def verify_dingtalk(timestamp: str, sign: str) -> bool:
    if not DINGTALK_SECRET:
        return True
    s = f"{timestamp}\n{DINGTALK_SECRET}"
    expected = base64.b64encode(hmac.new(DINGTALK_SECRET.encode(), s.encode(), hashlib.sha256).digest()).decode()
    return sign == expected


def parse_dingtalk_msg(data: dict) -> dict:
    text = data.get("text", {}).get("content", "").strip()
    sender = data.get("senderNick", "")
    source = "国际媒体"
    is_topic = False

    for prefix in ["话题", "话题:", "话题："]:
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
            is_topic = True
            break

    for prefix in ["写文章", "写一篇", "生成"]:
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
            break

    prefixes = {"bloomberg:": "Bloomberg（彭博社）", "wsj:": "Wall Street Journal（华尔街日报）",
                "nyt:": "New York Times（纽约时报）", "economist:": "The Economist（经济学人）"}
    for p, src in prefixes.items():
        if text.lower().startswith(p):
            source = src
            text = text[len(p):].strip()
            break

    extra = ""
    if "|" in text:
        parts = text.split("|", 1)
        text, extra = parts[0].strip(), parts[1].strip()

    return {"headline": text, "source": source, "extra_info": extra, "sender": sender, "is_topic": is_topic}


# ====================================================================
#                    7. Flask Web 后台
# ====================================================================

WEB_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>科技马前卒 - 管理后台</title>
  <style>
    *{margin:0;padding:0;box-sizing:border-box}body{font-family:"Noto Sans SC",-apple-system,sans-serif;background:#f5f5f7;color:#1d1d1f;min-height:100vh}.header{background:#fff;border-bottom:1px solid #e5e5e7;padding:16px 24px;display:flex;align-items:center;justify-content:space-between}.logo{font-size:1.15rem;font-weight:700}.container{max-width:800px;margin:32px auto;padding:0 20px}.card{background:#fff;border-radius:16px;padding:28px;margin-bottom:20px;box-shadow:0 1px 3px rgba(0,0,0,.06)}.card-title{font-size:1.05rem;font-weight:700;margin-bottom:18px}label{display:block;font-size:.82rem;font-weight:600;color:#86868b;margin-bottom:6px;text-transform:uppercase;letter-spacing:.04em}input,textarea,select{width:100%;padding:10px 12px;border:1px solid #d2d2d7;border-radius:10px;font-size:.92rem;font-family:inherit;background:#fafafa;outline:none;color:#1d1d1f;transition:all .2s}input:focus,textarea:focus,select:focus{border-color:#0071e3;box-shadow:0 0 0 3px rgba(0,113,227,.12);background:#fff}textarea{resize:vertical;min-height:70px}.row{margin-bottom:16px}.row2{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:16px}.tags{display:flex;flex-wrap:wrap;gap:6px}.tck{display:none}.tlb{display:inline-block;padding:5px 12px;border:1px solid #d2d2d7;border-radius:7px;font-size:.8rem;cursor:pointer;transition:all .2s;user-select:none}.tck:checked+.tlb{background:#0071e3;border-color:#0071e3;color:#fff}.btn{display:block;width:100%;padding:13px;border:none;border-radius:12px;font-size:.95rem;font-weight:600;font-family:inherit;cursor:pointer;transition:all .2s;text-align:center}.btn-p{background:#0071e3;color:#fff}.btn-p:hover{background:#0077ed}.btn-p:disabled{opacity:.5;cursor:default}.result{display:none}.result.show{display:block}.rh{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px}.ra{display:flex;gap:8px}.bs{padding:8px 14px;font-size:.82rem;border-radius:8px;border:1px solid #d2d2d7;background:#fff;color:#1d1d1f;cursor:pointer;font-family:inherit}.bs:hover{border-color:#0071e3;color:#0071e3}.bg{background:#30d158;color:#fff;border-color:#30d158}.bg:hover{background:#28c04e;color:#fff;border-color:#28c04e}.preview{background:#fafafa;border:1px solid #e5e5e7;border-radius:10px;padding:20px;max-height:480px;overflow-y:auto;line-height:1.9;font-size:.9rem}.preview h1{font-size:1.25rem;margin-bottom:14px}.preview h2{font-size:1.1rem;margin:20px 0 10px;border-bottom:1px solid #e5e5e7;padding-bottom:6px}.preview p{margin-bottom:12px}.preview hr{border:none;height:1px;background:#e5e5e7;margin:16px 0}.preview strong{color:#1d1d1f}.preview ul,.preview ol{padding-left:18px;margin-bottom:12px}.loading{text-align:center;padding:36px;color:#86868b;display:none}.spinner{display:inline-block;width:22px;height:22px;border:3px solid #e5e5e7;border-top-color:#0071e3;border-radius:50%;animation:spin .8s linear infinite;margin-bottom:10px}@keyframes spin{to{transform:rotate(360deg)}}.toast{position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:#1d1d1f;color:#fff;padding:10px 22px;border-radius:10px;font-size:.85rem;opacity:0;transition:opacity .3s;pointer-events:none;z-index:100}.toast.show{opacity:1}@media(max-width:640px){.row2{grid-template-columns:1fr}}
  </style>
</head>
<body>
  <div class="header"><div class="logo">🏇 科技马前卒 · 管理后台</div><div style="font-size:.8rem;color:#86868b">● 运行中</div></div>
  <div class="container">
    <div class="card">
      <div class="card-title">📝 提交话题</div>
      <form id="f" onsubmit="go(event)">
        <div class="row"><label>生成模式</label><div class="tags">
          <input type="radio" class="tck" id="mh" name="mode" value="headline" checked><label class="tlb" for="mh">📰 标题模式</label>
          <input type="radio" class="tck" id="mt" name="mode" value="topic"><label class="tlb" for="mt">🔍 话题模式（自动抓新闻）</label>
        </div></div>
        <div class="row"><label id="il">新闻标题</label><input type="text" id="hl" placeholder="粘贴英文标题..." required></div>
        <div class="row2"><div><label>来源</label><select id="src">
          <option value="Bloomberg（彭博社）">Bloomberg</option><option value="Wall Street Journal（华尔街日报）">WSJ</option>
          <option value="New York Times（纽约时报）">NYT</option><option value="The Economist（经济学人）">Economist</option>
          <option value="Reuters（路透社）">Reuters</option><option value="其他">其他</option>
        </select></div><div><label>发布到</label><select id="pt">
          <option value="both">网站 + 微信</option><option value="website">仅网站</option>
          <option value="wechat">仅微信</option><option value="none">不发布</option>
        </select></div></div>
        <div class="row"><label>标签</label><div class="tags">
          <input type="checkbox" class="tck" id="t1" name="tags" value="市场" checked><label class="tlb" for="t1">📊 市场</label>
          <input type="checkbox" class="tck" id="t2" name="tags" value="热点"><label class="tlb" for="t2">🔥 热点</label>
          <input type="checkbox" class="tck" id="t3" name="tags" value="中国"><label class="tlb" for="t3">🇨🇳 中国</label>
          <input type="checkbox" class="tck" id="t4" name="tags" value="地缘"><label class="tlb" for="t4">🌍 地缘</label>
          <input type="checkbox" class="tck" id="t5" name="tags" value="能源"><label class="tlb" for="t5">⚡ 能源</label>
          <input type="checkbox" class="tck" id="t6" name="tags" value="科技"><label class="tlb" for="t6">💻 科技</label>
        </div></div>
        <div class="row"><label>补充信息（可选）</label><textarea id="ei" placeholder="粘贴关键数据提高准确度..."></textarea></div>
        <button type="submit" class="btn btn-p" id="sb">生成文章</button>
      </form>
    </div>
    <div class="card loading" id="ld"><div class="spinner"></div><p>DeepSeek 正在写文章...</p></div>
    <div class="card result" id="rc">
      <div class="rh"><div class="card-title">📄 生成结果</div><div class="ra">
        <button class="bs" onclick="cp()">复制 Markdown</button>
        <button class="bs bg" onclick="pb()" id="pbtn">发布</button>
      </div></div>
      <div class="preview" id="pv"></div>
    </div>
  </div>
  <div class="toast" id="toast"></div>
  <script>
    let D=null;
    document.querySelectorAll('input[name="mode"]').forEach(r=>{r.addEventListener('change',function(){
      document.getElementById('il').textContent=this.value==='topic'?'话题关键词':'新闻标题';
      document.getElementById('hl').placeholder=this.value==='topic'?'如：美联储加息、特朗普关税...':'粘贴英文标题...';
    })});
    async function go(e){e.preventDefault();const v=document.getElementById('hl').value.trim();if(!v)return;
      const m=document.querySelector('input[name="mode"]:checked').value;
      const b={mode:m,source:document.getElementById('src').value,extra_info:document.getElementById('ei').value.trim(),
        tags:[...document.querySelectorAll('input[name="tags"]:checked')].map(c=>c.value),publish_to:document.getElementById('pt').value};
      if(m==='topic')b.topic=v;else b.headline=v;
      document.getElementById('sb').disabled=true;document.getElementById('ld').style.display='block';document.getElementById('rc').classList.remove('show');
      try{const r=await fetch('/api/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});
        const d=await r.json();if(d.success){D=d;document.getElementById('pv').innerHTML=d.html_preview;document.getElementById('rc').classList.add('show');toast('生成成功！');}
        else toast('失败：'+d.error);
      }catch(x){toast('请求失败：'+x.message);}finally{document.getElementById('sb').disabled=false;document.getElementById('ld').style.display='none';}}
    function cp(){if(D&&D.markdown)navigator.clipboard.writeText(D.markdown).then(()=>toast('已复制'));}
    async function pb(){if(!D)return;document.getElementById('pbtn').disabled=true;document.getElementById('pbtn').textContent='发布中...';
      try{const r=await fetch('/api/publish',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({title:D.title,content:D.content||D.markdown,tags:D.tags,source:D.source,publish_to:document.getElementById('pt').value})});
        const d=await r.json();toast(d.success?'发布成功！':'失败：'+JSON.stringify(d));}
      catch(x){toast('失败：'+x.message);}finally{document.getElementById('pbtn').disabled=false;document.getElementById('pbtn').textContent='发布';}}
    function toast(s){const t=document.getElementById('toast');t.textContent=s;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),3000);}
  </script>
</body>
</html>"""


def start_web_server():
    from flask import Flask, request as req, jsonify

    app = Flask(__name__)

    @app.route("/")
    def web_index():
        return WEB_HTML

    @app.route("/api/generate", methods=["POST"])
    def api_generate():
        data = req.get_json()
        mode = data.get("mode", "headline")
        try:
            if mode == "topic":
                topic = data.get("topic", "").strip()
                if not topic:
                    return jsonify({"success": False, "error": "话题不能为空"})
                article = generate_by_topic(topic)
            else:
                headline = data.get("headline", "").strip()
                if not headline:
                    return jsonify({"success": False, "error": "标题不能为空"})
                article = generate_by_headline(headline, data.get("source", "国际媒体"), data.get("extra_info", ""))

            import markdown as md_lib
            preview = md_lib.markdown(article["content_full"], extensions=["extra"])
            return jsonify({"success": True, "title": article["title"], "markdown": article["content_full"],
                            "content": article["content"], "html_preview": preview,
                            "source": data.get("source", ""), "tags": data.get("tags", ["热点"])})
        except Exception as e:
            traceback.print_exc()
            return jsonify({"success": False, "error": str(e)})

    @app.route("/api/publish", methods=["POST"])
    def api_publish():
        data = req.get_json()
        title, content = data.get("title", ""), data.get("content", "")
        tags, source = data.get("tags", ["热点"]), data.get("source", "")
        pt = data.get("publish_to", "both")
        if not content:
            return jsonify({"success": False, "error": "内容为空"})
        result = {"success": True, "website": None, "wechat": None}
        art = {"title": title, "content": content, "content_full": f"# {title}\n\n{content}", "headline": title, "source": source}
        if pt in ("both", "website"):
            try:
                result["website"] = publish_to_website(art, tags) or "未配置仓库"
            except Exception as e:
                result["website"] = f"失败: {e}"
        if pt in ("both", "wechat"):
            try:
                r = publish_to_wechat(title, content)
                result["wechat"] = f"成功 media_id={r.get('media_id')}" if r.get("media_id") else str(r)
            except Exception as e:
                result["wechat"] = f"失败: {e}"
        return jsonify(result)

    @app.route("/api/dingtalk", methods=["POST"])
    def api_dingtalk():
        if not verify_dingtalk(req.headers.get("timestamp", ""), req.headers.get("sign", "")):
            return jsonify({"msgtype": "text", "text": {"content": "签名失败"}})
        msg = parse_dingtalk_msg(req.get_json())
        if not msg["headline"]:
            return jsonify({"msgtype": "text", "text": {"content": "请发送标题，如：Bloomberg: xxx\n或：话题 美联储加息"}})
        try:
            art = generate_by_topic(msg["headline"]) if msg["is_topic"] else generate_by_headline(msg["headline"], msg["source"], msg["extra_info"])
            url = ""
            try: url = publish_to_website(art, ["热点"])
            except: pass
            try: publish_to_wechat(art["title"], art["content"])
            except: pass
            content = f"✅ {art['title']}"
            if url: content += f"\n🔗 {url}"
            return jsonify({"msgtype": "text", "text": {"content": content}})
        except Exception as e:
            return jsonify({"msgtype": "text", "text": {"content": f"❌ {e}"}})

    print("=" * 56)
    print("   🏇 科技马前卒 - 管理后台")
    print("=" * 56)
    print(f"   后台地址:  http://localhost:{FLASK_PORT}")
    print(f"   钉钉接口:  POST /api/dingtalk")
    print("=" * 56 + "\n")
    app.run(host="0.0.0.0", port=FLASK_PORT, debug=True)


# ====================================================================
#                        命令行入口
# ====================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="科技马前卒 - 全功能版")
    parser.add_argument("--cli", nargs="?", const="", default=None, help="命令行模式，传入话题关键词")
    parser.add_argument("--headline", type=str, help="标题模式：直接给英文标题")
    parser.add_argument("--source", type=str, default="国际媒体")
    parser.add_argument("--publish", action="store_true", help="自动发布到微信草稿箱")
    parser.add_argument("--save", type=str, default="", help="保存到文件")

    args = parser.parse_args()

    if args.cli is not None:
        if DEEPSEEK_API_KEY == "your-deepseek-api-key":
            print("❌ 请先配置 DEEPSEEK_API_KEY"); sys.exit(1)

        src_map = {"bloomberg": "Bloomberg（彭博社）", "wsj": "Wall Street Journal（华尔街日报）",
                    "nyt": "New York Times（纽约时报）", "economist": "The Economist（经济学人）"}

        if args.headline:
            src = src_map.get(args.source.lower(), args.source)
            print(f"[标题模式] {args.headline}\n")
            article = generate_by_headline(args.headline, src)
        elif args.cli:
            print(f"[话题模式] {args.cli}\n")
            article = generate_by_topic(args.cli)
        else:
            print("用法: python all_in_one.py --cli '美联储加息'")
            print("      python all_in_one.py --cli --headline 'Fed Raises Rates' --source bloomberg")
            sys.exit(0)

        print(f"\n标题: {article['title']}\n字数: {len(article['content'])}\n")

        if args.save:
            with open(args.save, "w", encoding="utf-8") as f:
                f.write(article["content_full"])
            print(f"已保存: {args.save}")

        if args.publish:
            try: publish_to_wechat(article["title"], article["content"])
            except Exception as e: print(f"微信发布失败: {e}")

        print("\n" + article["content_full"])
    else:
        start_web_server()
