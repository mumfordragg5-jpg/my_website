"""
科技马前卒 · 国际财经文章一键发布工具 (Google Gemini 驱动)

输入一个话题 → Gemini + Google Search 原生联网搜索最新新闻 → 生成深度文章 → 同时发布到：
  1. 微信公众号草稿箱（支持主公众号 + 科技马前卒）
  2. GitHub Pages 个人网站（通过 GitHub API 自动提交）
  3. 钉钉群通知

运行方式：
  - GitHub Actions（提交 Issue / 手动触发）
  - 命令行: python tools/gzh_news_writer_gemini.py gen "话题"
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import io
import json
import logging
import os
import re
import sys
import time
import urllib.parse
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ==================== 日志 ====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("gzh_gemini")

# ==================== 配置（从环境变量读取） ====================

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

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

TAG_RULES = [
    (["股市", "A股", "美股", "港股", "纳斯达克", "标普", "道琼斯", "stock", "market", "equity"], "市场"),
    (["地缘", "战争", "制裁", "军事", "导弹", "冲突", "中东", "俄乌", "geopolit", "war", "sanction"], "地缘"),
    (["中国", "中美", "人民币", "央行", "china", "beijing", "rmb"], "中国"),
    (["石油", "天然气", "能源", "OPEC", "oil", "gas", "energy"], "能源"),
    (["关税", "贸易", "tariff", "trade"], "热点"),
    (["美联储", "加息", "降息", "通胀", "fed", "inflation", "rate"], "热点"),
]

TAG_EMOJI = {"市场": "📊", "热点": "🔥", "中国": "🇨🇳", "地缘": "🌍", "能源": "⚡"}

# ==================== Gemini 联网生成文章 ====================

SYSTEM_PROMPT = (
    "你是一位资深财经自媒体作者，专注于解读国际财经新闻，面向中国读者撰写微信公众号文章。"
    "你的风格犀利、有深度、善用比喻，既专业又不枯燥。"
    "请使用 Google 搜索检索该话题的最新新闻动态，确保文章内容基于真实、最新的信息。"
)

ARTICLE_PROMPT_TEMPLATE = """今天是{today}。请搜索「{topic}」最近7天内的最新新闻。

写作要求：
请基于给定主题，创作一篇适合公众号传播的深度分析文章。

一、整体要求
- 面向普通读者，但不降低思考深度
- 信息密度高，但阅读轻松流畅
- 让读者产生“看懂了 + 有启发 + 想转发”的感觉
- 避免明显的“AI生成痕迹”，更像一个长期关注国际局势的作者在表达判断

二、结构参考（保持逻辑，但不要机械套用）
文章整体需要有清晰的递进关系，大致包含：
1. 一个有吸引力的标题（可以有悬念或冲突感，单独放在第一行）
2. 一个开头迅速切入重点，引发读者兴趣或认知反差
3. 简要交代事件本身（控制篇幅，抓重点，不铺陈）
4. 解释这件事为什么值得关注（补充必要背景）
5. 核心分析（重点展开，体现判断力，而不是复述信息）
6. 延伸到更现实层面的影响（例如经济、行业或普通人）
7. 用一句有力度的话收尾，让读者有“停顿感”

👉 注意：
结构是“隐形存在”的，不要写出明显的小标题套路或格式痕迹。

三、写作风格（关键）
- 以短句为主，但不要刻意碎片化
- 行文像“一个见过世面的朋友在讲清一件复杂的事”
- 允许适当观点，但避免绝对化结论
- 多用解释性表达，而不是口号式总结
- 可以用类比，但要自然，不要刻意“讲道理”
- 控制“总结句”“升华句”的密度，避免每段都在拔高

四、降低AI痕迹的关键约束
- 不要使用固定套路表达（如“首先/其次/最后”“值得注意的是”等）
- 不要刻意分点编号（如01/02/03）
- 避免“每段一个结论句”的刻意结构
- 不要反复强调“这意味着什么”，而是自然融入解释
- 避免情绪过满或刻意制造“震撼感”
- 不要为了“像文章”而写废话

五、信息表达要求
- 可以引用媒体或数据，但要自然融入语境
- 数据出现时，要顺带解释其意义，而不是孤立呈现
- 不追求全面，但要有“关键点判断”

六、结尾
结尾不需要刻意升华，可以是：一个判断、一个留白、或一句让人产生延伸思考的话。
最后保留固定引导：
关注我，带你看更多国际新闻。觉得有价值，点个「在看」，让更多人看到。

七、字数
1300–2000字

八、输出格式
- 第一行仅输出文章标题（不要带 Markdown #号或其他前缀）
- 第二行输出文章封面图的英文设计提示词，格式必须为：COVER_PROMPT: <简明英文视觉意象描述，用于AI生成16:9高级财经/科技质感插画，描述画面主体、色彩与光影，不要包含文字或水印词汇>
- 第三行空行
- 紧接着输出文章正文 Markdown 格式（可自然使用加粗 **重点**）
"""

def generate_article(topic: str) -> Dict[str, str]:
    if not GEMINI_API_KEY:
        raise ValueError("缺少 GEMINI_API_KEY 环境变量！请在 GitHub Secrets 或本地环境变量中设置 GEMINI_API_KEY。")
    today = datetime.now().strftime("%Y年%m月%d日")
    prompt = ARTICLE_PROMPT_TEMPLATE.format(topic=topic, today=today)

    log.info(f"Google Gemini 联网检索生成中: [{topic}] (模型: {GEMINI_MODEL})")
    t0 = time.time()

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": f"{SYSTEM_PROMPT}\n\n{prompt}"}
                ]
            }
        ],
        "tools": [
            {"google_search": {}}
        ],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 8192,
        }
    }

    max_retries = 2
    raw = ""
    session = requests.Session()
    if os.getenv("GEMINI_NO_PROXY", "").lower() in ("1", "true", "yes"):
        session.trust_env = False
    elif os.getenv("GEMINI_PROXY"):
        session.proxies = {
            "http": os.getenv("GEMINI_PROXY"),
            "https": os.getenv("GEMINI_PROXY"),
        }

    for attempt in range(max_retries):
        try:
            r = session.post(url, json=payload, timeout=90)
            if r.status_code == 200:
                res = r.json()
                candidates = res.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts:
                        raw = "".join(p.get("text", "") for p in parts if p.get("text")).strip()
                        break
            else:
                log.warning(f"Gemini API 返回 HTTP {r.status_code}: {r.text[:300]}")
        except Exception as e:
            log.warning(f"Gemini 请求异常 (第{attempt+1}次): {e}")
            time.sleep(2)

    if not raw:
        raise RuntimeError(f"Gemini 未能成功生成文章内容，请检查 API Key 或网络连通性。")

    log.info(f"Gemini 生成完成, 耗时 {time.time()-t0:.1f}s, 字数 {len(raw)}")

    lines = raw.split("\n")
    title, cover_prompt, content_lines = "", "", []
    for line in lines:
        s = line.strip()
        if not title and s:
            title = re.sub(r'^[#\s\*\-]+', '', s).strip()
            continue
        if not cover_prompt and s.upper().startswith("COVER_PROMPT:"):
            cover_prompt = s.split(":", 1)[1].strip()
            continue
        content_lines.append(line)
    
    content = "\n".join(content_lines).strip()
    
    cleaned_lines = []
    preamble_done = False
    for line in content.split("\n"):
        s = line.strip()
        if not preamble_done:
            if s and any(s.startswith(kw) for kw in ["好的", "根据您", "让我", "由于", "我将", "我会", "根据搜索", "搜索结果", "很抱歉"]):
                continue
            else:
                preamble_done = True
        cleaned_lines.append(line)
    
    final_content = "\n".join(cleaned_lines).strip()
    
    if not cover_prompt:
        cover_prompt = (
            f"High-end editorial conceptual 3D illustration about global economics, finance, technology, {topic}, "
            "sleek modern minimalist aesthetic, cinematic studio lighting, dramatic contrast, vibrant colors, "
            "clean composition, highly detailed, 8k resolution"
        )

    return {"title": title, "content": final_content, "cover_prompt": cover_prompt}

# ==================== AI 封面图生成与裁剪 ====================

def generate_cover_image(topic: str, title: str, cover_prompt: str = "", filename: str = "cover_temp.jpg") -> Optional[str]:
    """使用 Pollinations (Flux) 生成 2.35:1 无水印微信标准封面图"""
    if not cover_prompt:
        cover_prompt = (
            f"High-end editorial conceptual 3D illustration about global economics, technology, {topic}, "
            "sleek modern minimalist aesthetic, cinematic studio lighting, dramatic contrast, vibrant colors, "
            "clean composition, highly detailed, 8k resolution"
        )
    # 强制约束无文本无水印
    full_prompt = f"{cover_prompt.strip()}, no text, no watermark, no words, clean editorial, 16:9 aspect ratio"
    encoded = urllib.parse.quote(full_prompt)
    url = f"https://image.pollinations.ai/prompt/{encoded}?width=1280&height=720&nologo=true"

    log.info(f"AI 封面图生成中: [{topic}] -> Prompt: {cover_prompt[:80]}...")
    t0 = time.time()

    img_bytes = None
    for attempt in range(2):
        try:
            r = requests.get(url, timeout=50)
            if r.status_code == 200 and len(r.content) > 2000 and "image" in r.headers.get("content-type", ""):
                img_bytes = r.content
                break
            else:
                log.warning(f"生图接口返回异常状态 (第{attempt+1}次): {r.status_code}")
        except Exception as e:
            log.warning(f"生图请求失败 (第{attempt+1}次): {e}")
            time.sleep(2)

    if not img_bytes:
        log.warning("AI 封面图生成失败，后续将降级使用默认封面。")
        return None

    try:
        if HAS_PIL:
            img = Image.open(io.BytesIO(img_bytes))
            w, h = img.size
            # 裁剪底部 35px 水印并按微信头条大图 2.35:1 比例居中裁切
            target_h = int(w / 2.35)
            top = max(0, (h - 35 - target_h) // 2)
            cropped = img.crop((0, top, w, top + target_h))
            cropped.save(filename, "JPEG", quality=92)
        else:
            with open(filename, "wb") as f:
                f.write(img_bytes)
        log.info(f"AI 封面图就绪: {filename} (耗时 {time.time()-t0:.1f}s)")
        return filename
    except Exception as e:
        log.warning(f"封面图裁剪处理失败: {e}")
        with open(filename, "wb") as f:
            f.write(img_bytes)
        return filename

# ==================== 微信公众号素材上传 ====================

def upload_wx_media(token: str, img_path: str) -> Optional[str]:
    """上传永久图片素材到微信公众号素材库，返回 media_id（草稿箱必须使用永久素材ID）"""
    if not img_path or not os.path.exists(img_path):
        return None
    url = f"https://api.weixin.qq.com/cgi-bin/material/add_material?access_token={token}&type=image"
    try:
        with open(img_path, "rb") as f:
            files = {"media": ("cover.jpg", f, "image/jpeg")}
            r = requests.post(url, files=files, timeout=30)
        res = r.json()
        media_id = res.get("media_id")
        if media_id:
            log.info(f"微信永久素材上传成功, media_id: {media_id}")
            return media_id
        else:
            log.warning(f"微信素材上传失败: {res}")
            return None
    except Exception as e:
        log.warning(f"微信素材上传异常: {e}")
        return None

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
                            source: str, date_str: str, cover_web_url: Optional[str] = None) -> str:
    body_html = md_to_website_body(md_content)
    reading_min = max(5, len(md_content) // 400)
    tag_spans = "\n".join(
        f'                    <span class="card-tag">{TAG_EMOJI.get(t, "🔥")} {t}</span>'
        for t in tags
    )
    cover_hero_html = ""
    if cover_web_url:
        cover_hero_html = f'''            <div class="article-hero-cover" style="margin: 0 0 30px; border-radius: var(--radius); overflow: hidden; box-shadow: var(--shadow-md);">
                <img src="../{cover_web_url}" alt="{title}" style="width: 100%; height: auto; display: block;">
            </div>\n'''

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
{cover_hero_html}            <div class="article-content">
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
                          source: str, date_str: str, cover_web_url: Optional[str] = None) -> str:
    tag_spans = "\n".join(
        f'                        <span class="card-tag{" tag-secondary" if i > 0 else ""}">{TAG_EMOJI.get(t, "🔥")} {t}</span>'
        for i, t in enumerate(tags)
    )
    tags_str = " ".join(tags)
    cover_html = ""
    if cover_web_url:
        cover_html = f'''
                <div class="card-cover">
                    <a href="articles/{slug}.html"><img src="{cover_web_url}" alt="{title}" loading="lazy"></a>
                </div>'''

    return f'''
            <div class="article-card fade-in" data-tags="{tags_str}" data-title="{title}" data-search="{title} {tags_str} {source}">{cover_html}
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
                     thumb_media_id: str = None, author: str = None,
                     cover_img_path: str = None) -> Dict[str, Any]:
    appid = appid or WX_APPID
    appsecret = appsecret or WX_APPSECRET
    author = author or WX_AUTHOR
    r = requests.get("https://api.weixin.qq.com/cgi-bin/token", params={
        "grant_type": "client_credential", "appid": appid, "secret": appsecret,
    }, timeout=15)
    r.raise_for_status()
    token = r.json().get("access_token")
    if not token:
        raise RuntimeError(f"获取 access_token 失败: {r.json()}")

    # 优先自动上传专属 AI 封面图到微信公众号素材库
    actual_thumb_id = None
    if cover_img_path and os.path.exists(cover_img_path):
        log.info(f"正在自动上传专属 AI 封面到微信公众号 ({author})...")
        actual_thumb_id = upload_wx_media(token, cover_img_path)

    if not actual_thumb_id:
        actual_thumb_id = thumb_media_id or WX_THUMB_MEDIA_ID
        log.info(f"使用默认封面 thumb_media_id: {actual_thumb_id}")
    else:
        log.info(f"成功绑定专属 AI 封面 thumb_media_id: {actual_thumb_id}")

    payload = {"articles": [{
        "title": title, "content": html_content, "content_source_url": "",
        "thumb_media_id": actual_thumb_id, "author": author,
        "digest": title[:60], "show_cover_pic": 0,
        "need_open_comment": 1, "only_fans_can_comment": 0,
    }]}
    r2 = requests.post(
        f"https://api.weixin.qq.com/cgi-bin/draft/add?access_token={token}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        timeout=30)
    r2.raise_for_status()
    res = r2.json()

    if res.get("errcode") and res.get("errcode") != 0:
        default_thumb = thumb_media_id or (WX_THUMB_MEDIA_ID2 if author == WX_AUTHOR2 else WX_THUMB_MEDIA_ID)
        if actual_thumb_id != default_thumb and default_thumb:
            log.warning(f"微信草稿添加报错(errcode={res.get('errcode')}: {res.get('errmsg')})，正在降级使用默认封面重试...")
            payload["articles"][0]["thumb_media_id"] = default_thumb
            r2_retry = requests.post(
                f"https://api.weixin.qq.com/cgi-bin/draft/add?access_token={token}",
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json; charset=utf-8"},
                timeout=30)
            r2_retry.raise_for_status()
            res_retry = r2_retry.json()
            if res_retry.get("errcode") and res_retry.get("errcode") != 0:
                raise RuntimeError(f"微信草稿箱添加失败: errcode={res_retry.get('errcode')}, errmsg={res_retry.get('errmsg')}")
            return res_retry
        else:
            raise RuntimeError(f"微信草稿箱添加失败: errcode={res.get('errcode')}, errmsg={res.get('errmsg')}")

    return res

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

def _gh_put_binary_file(path: str, data: bytes, message: str, sha: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "message": message,
        "content": base64.b64encode(data).decode("ascii"),
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
                   source: str, date_str: str,
                   cover_img_path: Optional[str] = None) -> Dict[str, str]:
    results = {}
    cover_web_url = None

    if cover_img_path and os.path.exists(cover_img_path):
        cover_gh_path = f"assets/covers/{slug}.jpg"
        try:
            with open(cover_img_path, "rb") as f:
                img_data = f.read()
            existing_cover = _gh_get_file(cover_gh_path)
            _gh_put_binary_file(cover_gh_path, img_data, f"Add cover: {title}",
                                existing_cover["sha"] if existing_cover else None)
            cover_web_url = f"assets/covers/{slug}.jpg"
            results["cover_image"] = cover_gh_path
            log.info(f"GitHub: 封面图已上传 -> {cover_gh_path}")
        except Exception as e:
            log.warning(f"GitHub 封面图上传失败: {e}")

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
        new_card = build_index_card_html(slug, title, excerpt, tags, source, date_str, cover_web_url=cover_web_url)

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
                 publish_gh: bool = True, generate_cover: bool = True) -> Dict[str, Any]:
    log.info(f"{'='*50}")
    log.info(f"话题: {topic} (使用 Google Gemini API)")
    log.info(f"{'='*50}")
    result: Dict[str, Any] = {"topic": topic, "status": "processing"}

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

    # AI 封面图生成
    cover_img_path = None
    if generate_cover:
        cover_prompt = article.get("cover_prompt", "")
        cover_filename = f"cover_{slug}.jpg"
        cover_img_path = generate_cover_image(topic, title, cover_prompt, cover_filename)
        if cover_img_path:
            result["cover_image"] = cover_img_path

    if publish_wx:
        try:
            wx_html = md_to_wx_html(content_md)
            wx_result = publish_wx_draft(title, wx_html, cover_img_path=cover_img_path)
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
                thumb_media_id=WX_THUMB_MEDIA_ID2, author=WX_AUTHOR2,
                cover_img_path=cover_img_path)
            result["wx_result2"] = wx_result2
            log.info(f"公众号2: media_id={wx_result2.get('media_id', 'N/A')}")
        except Exception as e:
            log.error(f"公众号2失败: {e}")
            result["wx_error2"] = str(e)

    if publish_gh and GITHUB_TOKEN:
        try:
            page_html = build_article_page_html(
                title, content_md, tags, source_hint, date_str,
                cover_web_url=f"assets/covers/{slug}.jpg" if cover_img_path else None
            )
            gh_result = push_to_github(
                slug, page_html, content_md, title, excerpt, tags, source_hint, date_short,
                cover_img_path=cover_img_path
            )
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
    parser = argparse.ArgumentParser(description="科技马前卒 · 文章一键发布 (Gemini)")
    sub = parser.add_subparsers(dest="command")

    gen_p = sub.add_parser("gen", help="生成并发布文章")
    gen_p.add_argument("topic", type=str, help="话题")
    gen_p.add_argument("--source", type=str, default="综合")
    gen_p.add_argument("--no-wx", action="store_true", help="不发布到公众号")
    gen_p.add_argument("--no-wx2", action="store_true", help="不发布到公众号2（科技马前卒）")
    gen_p.add_argument("--no-gh", action="store_true", help="不发布到 GitHub")
    gen_p.add_argument("--no-cover", action="store_true", help="不生成 AI 封面图")
    gen_p.add_argument("--save", type=str, default="", help="保存 Markdown 到文件")

    args = parser.parse_args()

    if args.command == "gen":
        if not GEMINI_API_KEY:
            print("错误：请设置环境变量 GEMINI_API_KEY")
            exit(1)

        result = run_pipeline(
            topic=args.topic,
            source_hint=args.source,
            publish_wx=not args.no_wx,
            publish_wx2=not args.no_wx2,
            publish_gh=not args.no_gh,
            generate_cover=not args.no_cover,
        )
        print(f"\n标题: {result['title']}")
        if result.get("cover_image"):
            print(f"封面: {result['cover_image']}")
        if result.get("gh_url"):
            print(f"网站: {result['gh_url']}")
        if result.get("wx_result", {}).get("media_id"):
            print(f"公众号: {result['wx_result']['media_id']}")
        if result.get("wx_result2", {}).get("media_id"):
            print(f"公众号2: {result['wx_result2']['media_id']}")

        if args.save:
            with open(args.save, "w", encoding="utf-8") as f:
                f.write(f"# {result['title']}\n\n{result['content_md']}")
            print(f"已保存: {args.save}")
    else:
        parser.print_help()
