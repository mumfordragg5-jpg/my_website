"""
科技马前卒 - 网站自动发布模块

将生成的文章自动发布到 GitHub Pages 网站：
1. 生成文章 HTML 页面
2. 更新首页文章列表
3. Git commit & push 触发自动部署
"""

import os
import re
import datetime
import subprocess
import markdown
from config import GITHUB_REPO_PATH, GITHUB_AUTO_PUSH

TAG_MAP = {
    "市场": ("market", "📊 市场"),
    "热点": ("hotspot", "🔥 热点"),
    "中国": ("china", "🇨🇳 中国"),
    "地缘": ("geopolitics", "🌍 地缘"),
    "能源": ("energy", "⚡ 能源"),
    "科技": ("tech", "💻 科技"),
    "贸易": ("trade", "📦 贸易"),
}

SOURCE_SHORT = {
    "Bloomberg": "Bloomberg",
    "彭博社": "Bloomberg",
    "Wall Street Journal": "WSJ",
    "华尔街日报": "WSJ",
    "New York Times": "NYT",
    "纽约时报": "NYT",
    "The Economist": "Economist",
    "经济学人": "Economist",
    "Reuters": "Reuters",
    "路透社": "Reuters",
    "Financial Times": "FT",
    "金融时报": "FT",
}


def publish_to_website(article: dict, tags: list = None) -> str:
    """
    将文章发布到网站。

    Args:
        article: generate_article() 返回的 dict
        tags: 标签列表，如 ["市场", "中国"]

    Returns:
        文章 URL 路径
    """
    if not GITHUB_REPO_PATH:
        return ""

    tags = tags or ["热点"]
    date_str = datetime.date.today().strftime("%Y-%m-%d")
    slug = _make_slug(article["title"])
    filename = f"{slug}.html"

    html_content = _render_article_html(article, tags, date_str)
    article_path = os.path.join(GITHUB_REPO_PATH, "articles", filename)
    os.makedirs(os.path.dirname(article_path), exist_ok=True)

    with open(article_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    _update_index(article, tags, date_str, filename)

    if GITHUB_AUTO_PUSH:
        _git_push(article["title"])

    return f"articles/{filename}"


def _make_slug(title: str) -> str:
    slug = re.sub(r'[^\w\u4e00-\u9fff-]', '', title.replace(" ", "-"))
    if len(slug) > 40:
        slug = slug[:40]
    return slug


def _get_source_short(source: str) -> str:
    for key, val in SOURCE_SHORT.items():
        if key in source:
            return val
    return "Media"


def _md_to_html(md_content: str) -> str:
    """Markdown 转 HTML，跳过第一行标题"""
    lines = md_content.split("\n")
    body_lines = []
    skip_first_heading = True
    for line in lines:
        if skip_first_heading and line.strip().startswith("# "):
            skip_first_heading = False
            continue
        body_lines.append(line)

    return markdown.markdown("\n".join(body_lines), extensions=["extra"])


def _render_article_html(article: dict, tags: list, date_str: str) -> str:
    tag_html = ""
    for t in tags:
        if t in TAG_MAP:
            _, label = TAG_MAP[t]
            tag_html += f'    <span class="card-tag">{label}</span>\n'

    source_short = _get_source_short(article["source"])
    body_html = _md_to_html(article["content"])

    return f"""<!DOCTYPE html>
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

  <header class="site-header">
    <nav class="nav-inner">
      <a href="../index.html" class="site-logo">
        <span class="logo-icon">🏇</span>科技马前卒
      </a>
      <div class="nav-right">
        <ul class="nav-links" id="navLinks">
          <li><a href="../index.html">首页</a></li>
          <li><a href="../index.html#articles">文章</a></li>
          <li><a href="../index.html#about">关于</a></li>
        </ul>
        <button class="theme-toggle" id="themeToggle" aria-label="切换主题">🌙</button>
        <button class="menu-toggle" id="menuToggle" aria-label="菜单">
          <span></span><span></span><span></span>
        </button>
      </div>
    </nav>
  </header>

  <div class="back-link"><a href="../index.html">← 返回首页</a></div>

  <header class="article-header">
{tag_html}
    <h1 class="article-title">{article["title"]}</h1>
    <div class="article-meta-line">
      <span>📅 {date_str}</span>
      <span>📖 约 8 分钟阅读</span>
      <span>📰 来源: {source_short}</span>
    </div>
  </header>

  <div class="article-body">
    <div class="article-content">
{body_html}
    </div>
  </div>

  <footer class="site-footer">
    <div class="footer-inner">
      <ul class="footer-links">
        <li><a href="../index.html">首页</a></li>
        <li><a href="../index.html#articles">文章</a></li>
        <li><a href="../index.html#about">关于</a></li>
      </ul>
      <p>&copy; 2026 科技马前卒 · 帮中国人读懂西方财经头条</p>
    </div>
  </footer>

  <script src="../js/main.js"></script>
</body>
</html>"""


def _update_index(article: dict, tags: list, date_str: str, filename: str):
    """在 index.html 的 article-grid 中插入新文章卡片"""
    index_path = os.path.join(GITHUB_REPO_PATH, "index.html")
    if not os.path.exists(index_path):
        return

    with open(index_path, "r", encoding="utf-8") as f:
        html = f.read()

    tag_keys = ",".join(TAG_MAP[t][0] for t in tags if t in TAG_MAP)
    search_keywords = article["title"].replace("，", " ").replace("？", " ").replace("！", " ")
    source_short = _get_source_short(article["source"])

    tag_badges = ""
    for i, t in enumerate(tags):
        if t in TAG_MAP:
            _, label = TAG_MAP[t]
            cls = "card-tag" if i == 0 else "card-tag tag-secondary"
            tag_badges += f'          <span class="{cls}">{label}</span>\n'

    excerpt = article["content"][:200].replace("#", "").replace("*", "").replace("\n", " ").strip()
    if len(excerpt) > 100:
        excerpt = excerpt[:100] + "..."

    card_html = f"""
    <article class="article-card fade-in" data-tags="{tag_keys}" data-title="{article['title']}" data-search="{search_keywords}">
      <div class="card-body">
        <div class="card-tags-row">
{tag_badges}        </div>
        <h2 class="card-title">
          <a href="articles/{filename}">{article["title"]}</a>
        </h2>
        <p class="card-excerpt">{excerpt}</p>
        <div class="card-footer">
          <div class="card-meta">
            <span>{date_str}</span>
            <span>约 8 分钟</span>
          </div>
          <span class="card-source">{source_short}</span>
        </div>
      </div>
    </article>
"""

    marker = '<div class="article-grid" id="articleGrid">'
    if marker in html:
        html = html.replace(marker, marker + card_html, 1)

        with open(index_path, "w", encoding="utf-8") as f:
            f.write(html)

    _update_article_count(index_path)


def _update_article_count(index_path: str):
    """更新首页的文章计数"""
    with open(index_path, "r", encoding="utf-8") as f:
        html = f.read()

    count = html.count('class="article-card')
    html = re.sub(
        r'(<span class="stat-number" id="articleCount">)\d+(</span>)',
        f"\\g<1>{count}\\2",
        html,
    )

    with open(index_path, "w", encoding="utf-8") as f:
        f.write(html)


def _git_push(title: str):
    """Git add, commit, push"""
    try:
        subprocess.run(["git", "add", "-A"], cwd=GITHUB_REPO_PATH, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", f"Publish: {title[:50]}"],
            cwd=GITHUB_REPO_PATH, check=True, capture_output=True,
        )
        subprocess.run(["git", "push"], cwd=GITHUB_REPO_PATH, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        print(f"Git push failed: {e.stderr.decode() if e.stderr else e}")
