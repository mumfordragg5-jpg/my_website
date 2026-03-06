"""
科技马前卒 - 新闻聚合模块

聚合 Google News RSS / NewsAPI / Bing News 多源新闻。
原始代码保留，仅提取为独立模块。
"""

import re
import time
import xml.etree.ElementTree as ET
from typing import Dict, List

import requests

from config import NEWSAPI_KEY, MEDIA_SOURCES


def _headers() -> Dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
    }


def fetch_google_news_rss(query: str, num: int = 10) -> List[Dict[str, str]]:
    url = "https://news.google.com/rss/search"
    params = {"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"}
    try:
        r = requests.get(url, params=params, headers=_headers(), timeout=20)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        items = root.findall(".//item")
        results = []
        for item in items[:num]:
            title = item.findtext("title", "")
            source = item.findtext("source", "")
            pub_date = item.findtext("pubDate", "")
            link = item.findtext("link", "")
            description = item.findtext("description", "")
            description = re.sub(r"<[^>]+>", "", description).strip()
            results.append({
                "title": title, "source": source, "date": pub_date,
                "link": link, "summary": description[:500],
            })
        return results
    except Exception as e:
        print(f"[Google News RSS] 抓取失败: {e}")
        return []


def fetch_newsapi(query: str, num: int = 10) -> List[Dict[str, str]]:
    if not NEWSAPI_KEY:
        return []
    url = "https://newsapi.org/v2/everything"
    params = {
        "q": query, "language": "en", "sortBy": "publishedAt",
        "pageSize": num, "apiKey": NEWSAPI_KEY,
    }
    try:
        r = requests.get(url, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
        results = []
        for article in data.get("articles", []):
            results.append({
                "title": article.get("title", ""),
                "source": article.get("source", {}).get("name", ""),
                "date": article.get("publishedAt", ""),
                "link": article.get("url", ""),
                "summary": (article.get("description") or "")[:500],
            })
        return results
    except Exception as e:
        print(f"[NewsAPI] 抓取失败: {e}")
        return []


def fetch_bing_news(query: str, num: int = 10) -> List[Dict[str, str]]:
    url = "https://www.bing.com/news/search"
    params = {"q": query, "format": "rss", "count": num}
    try:
        r = requests.get(url, params=params, headers=_headers(), timeout=20)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        items = root.findall(".//item")
        results = []
        for item in items[:num]:
            title = item.findtext("title", "")
            source = item.findtext("source", "")
            pub_date = item.findtext("pubDate", "")
            link = item.findtext("link", "")
            description = item.findtext("description", "")
            description = re.sub(r"<[^>]+>", "", description).strip()
            results.append({
                "title": title, "source": source, "date": pub_date,
                "link": link, "summary": description[:500],
            })
        return results
    except Exception as e:
        print(f"[Bing News] 抓取失败: {e}")
        return []


def aggregate_news(topic: str, num: int = 15) -> List[Dict[str, str]]:
    """聚合多来源新闻并去重"""
    all_news = []
    print(f"[新闻聚合] 正在搜索话题: {topic}")

    google_results = fetch_google_news_rss(topic, num)
    print(f"  - Google News: {len(google_results)} 条")
    all_news.extend(google_results)
    time.sleep(0.5)

    newsapi_results = fetch_newsapi(topic, num)
    if newsapi_results:
        print(f"  - NewsAPI: {len(newsapi_results)} 条")
        all_news.extend(newsapi_results)
        time.sleep(0.5)

    bing_results = fetch_bing_news(topic, num)
    print(f"  - Bing News: {len(bing_results)} 条")
    all_news.extend(bing_results)

    seen_titles = set()
    unique = []
    for item in all_news:
        normalized = item["title"].strip().lower()
        if normalized and normalized not in seen_titles:
            seen_titles.add(normalized)
            unique.append(item)

    print(f"[新闻聚合] 去重后共 {len(unique)} 条新闻\n")
    return unique


def identify_source(source_name: str) -> str:
    lower = source_name.lower()
    for key, cn_name in MEDIA_SOURCES.items():
        if key in lower:
            return cn_name
    return source_name


def format_news_for_prompt(news_list: List[Dict[str, str]], max_items: int = 12) -> str:
    lines = []
    for i, item in enumerate(news_list[:max_items], 1):
        source_cn = identify_source(item.get("source", ""))
        line = f"{i}. [{source_cn}] {item['title']}"
        if item.get("summary"):
            line += f"\n   摘要: {item['summary']}"
        lines.append(line)
    return "\n\n".join(lines)
