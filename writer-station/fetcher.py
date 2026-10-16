"""
增量信息源 —— 为改写提供"原文没有的公开信息"

为什么必须有这一步：
  只把别人文章换词重写，法律上仍属侵权（保护的是"表达"而非"思想"），
  平台侧也能通过语义指纹识别。真正降低风险的做法是加入**增量**——
  公开可查的政策、数据、官方口径，让成品具备独立的信息价值。

当前接入：百度资讯搜索（已验证可用，无需登录）
"""

import html as ht
import re
import ssl
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def _ctx():
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c


def _strip(s):
    return ht.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def baidu_news(keyword, limit=8):
    """百度资讯搜索：返回 [{title, source, snippet}]"""
    q = urllib.parse.quote(keyword)
    url = "https://www.baidu.com/s?rtt=1&bsst=1&cl=2&tn=news&word=" + q
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://www.baidu.com/",
    })
    body = urllib.request.urlopen(req, timeout=25, context=_ctx()).read().decode("utf-8", "replace")

    items = []
    # 百度资讯结果块
    for blk in re.split(r'<div[^>]*class="result-op[^"]*"|<div[^>]*class="result[^"]*"', body)[1:]:
        mt = re.search(r'<h3[^>]*>\s*<a[^>]*>(.*?)</a>', blk, re.S)
        if not mt:
            continue
        title = _strip(mt.group(1))
        if len(title) < 6:
            continue
        ms = re.search(r'class="c-span-last[^"]*"[^>]*>(.*?)</div>', blk, re.S) \
            or re.search(r'<span[^>]*class="c-color-text"[^>]*>(.*?)</span>', blk, re.S)
        snippet = _strip(ms.group(1)) if ms else ""
        msrc = re.search(r'class="c-color-gray[^"]*"[^>]*>(.*?)</', blk, re.S)
        items.append({
            "title": title,
            "source": _strip(msrc.group(1)) if msrc else "",
            "snippet": snippet[:220],
        })
        if len(items) >= limit:
            break
    return items


def gather_increments(keywords, limit_each=5):
    """按关键词收集公开信息，去重后返回"""
    seen, out = set(), []
    for kw in keywords:
        try:
            for it in baidu_news(kw, limit_each):
                key = it["title"]
                if key in seen:
                    continue
                seen.add(key)
                it["keyword"] = kw
                out.append(it)
        except Exception as e:
            out.append({"keyword": kw, "title": "", "source": "",
                        "snippet": "", "error": "%s: %s" % (type(e).__name__, e)})
    return out


if __name__ == "__main__":
    import io
    import json
    import os
    for kw in ["养老金 上调", "老年人 情感需求"]:
        print("=" * 50)
        print(kw)
        for x in baidu_news(kw, 6):
            print(" -", x["title"][:60], "|", x["source"])
    res = gather_increments(["养老金 上调 政策"], 5)
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "increments_sample.json")
    io.open(p, "w", encoding="utf-8").write(json.dumps(res, ensure_ascii=False, indent=2))
    print("saved", p, len(res))
