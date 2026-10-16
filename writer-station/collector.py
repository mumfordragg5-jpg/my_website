"""
低频采集模块 —— 搜狗微信搜索

为什么是"低频"：
  实测搜狗的 token 是页级共享的，同一页链接只能成功解析极少数几次，
  之后跳转页与搜索页都会返回验证码（antispider）。
  因此本模块的策略是：小批量 + 大间隔 + 重试退避，而不是一次性拉几十条。

两个阶段可分开跑：
  list_only  —— 只抓标题/摘要/时间（快，不易被封）★推荐日常用
  with_body  —— 连带抓正文（慢，强反爬，建议每次 ≤3 条）
"""

import html as ht
import json
import random
import re
import ssl
import time
import urllib.parse
import urllib.request

import db

UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
]


class RateLimited(RuntimeError):
    pass


def _ctx():
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c


def _headers(ua):
    return {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }


def _strip(s):
    return ht.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def _clean_red(s):
    return _strip(re.sub(r"<!--red_beg-->|<!--red_end-->", "", s or ""))


class Collector:
    def __init__(self, delay=25.0):
        self.delay = float(delay)
        self.ua = random.choice(UA_POOL)
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())

    # ---------- 搜索列表 ----------
    def search(self, kw, page=1):
        url = "https://weixin.sogou.com/weixin?type=2&query=%s&page=%d" % (
            urllib.parse.quote(kw), page)
        req = urllib.request.Request(url, headers={**_headers(self.ua),
                                                  "Referer": "https://weixin.sogou.com/"})
        body = self.op.open(req, timeout=25).read().decode("utf-8", "replace")
        if "antispider" in body or "请输入验证码" in body:
            raise RateLimited("搜狗反爬：搜索页返回验证码")

        blocks = re.split(r'<li id="sogou_vr_11002601_box_', body)[1:]
        items = []
        for b in blocks:
            mt = re.search(r'<h3>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', b, re.S)
            if not mt:
                continue
            md = re.search(r"timeConvert\('(\d+)'\)", b)
            ms = re.search(r'<p class="txt-info"[^>]*>(.*?)</p>', b, re.S)
            items.append({
                "title": _clean_red(mt.group(2)),
                "summary": _clean_red(ms.group(1)) if ms else "",
                "published_ts": int(md.group(1)) if md else 0,
                "sogou_link": ht.unescape(mt.group(1)),
                "keyword": kw,
                "source": "sogou-weixin",
            })
        return items

    # ---------- 跳转解析 ----------
    def resolve(self, sogou_link):
        full = sogou_link if sogou_link.startswith("http") else "https://weixin.sogou.com" + sogou_link
        req = urllib.request.Request(full, headers={**_headers(self.ua),
                                                   "Referer": "https://weixin.sogou.com/"})
        jump = self.op.open(req, timeout=25).read().decode("utf-8", "replace")
        if "antispider" in jump or "验证码" in jump:
            raise RateLimited("搜狗反爬：跳转页返回验证码")
        real = "".join(re.findall(r"url\s*\+=\s*'([^']*)'", jump)).replace("@", "")
        return real if real.startswith("http") else ""

    # ---------- 正文 ----------
    def article(self, url):
        req = urllib.request.Request(url, headers={**_headers(self.ua),
                                                  "Referer": "https://weixin.sogou.com/"})
        art = self.op.open(req, timeout=30).read().decode("utf-8", "replace")
        mt = (re.search(r'var msg_title\s*=\s*[\'"](.*?)[\'"]', art)
              or re.search(r'<h1[^>]*class="rich_media_title"[^>]*>(.*?)</h1>', art, re.S))
        ma = (re.search(r'var nickname\s*=\s*[\'"](.*?)[\'"]', art)
              or re.search(r'id="js_name"[^>]*>(.*?)<', art, re.S))

        body = ""
        start = re.search(r'<div[^>]*id="js_content"[^>]*>', art)
        if start:
            seg = art[start.end(): start.end() + 200000]
            end = seg.find('<div id="js_pc_qr_code"')
            if end == -1:
                end = seg.find('<div class="rich_media_tool')
            if end == -1:
                end = min(len(seg), 120000)
            body = self.clean_body(seg[:end])
        if not body:
            md = re.search(r'<meta property="og:description" content="([^"]*)"', art)
            body = _strip(md.group(1)) if md else ""

        return {
            "real_title": _strip(mt.group(1)) if mt else "",
            "real_account": _strip(ma.group(1)) if ma else "",
            "body": body,
            "body_len": len(body),
        }

    @staticmethod
    def clean_body(raw):
        if not raw:
            return ""
        s = re.sub(r"<script\b.*?</script>", "", raw, flags=re.S | re.I)
        s = re.sub(r"<style\b.*?</style>", "", s, flags=re.S | re.I)
        s = re.sub(r"<!--.*?-->", "", s, flags=re.S)
        s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
        s = re.sub(r"</(p|section|div|h[1-6]|li|tr|blockquote)\s*>", "\n", s, flags=re.I)
        s = _strip(s)
        s = re.split(r"var\s+first_sceen__time|document\.addEventListener|function\s*\(e\)|预览时标签不可点", s)[0]
        s = s.replace("\u200b", "").replace("\ufeff", "")
        s = re.sub(r"[ \t\u00a0]+", " ", s)
        s = re.sub(r"\n\s*\n+", "\n", s)
        return s.strip()

    # ---------- 重试包装 ----------
    def _jitter(self):
        """固定频率容易被识别，加 ±30% 抖动"""
        return self.delay * random.uniform(0.7, 1.35)

    def _retry(self, fn, *a, attempts=3):
        last = None
        for i in range(attempts):
            try:
                return fn(*a)
            except RateLimited as e:
                last = e
                wait = self.delay * (i + 2)
                print("  [rate-limit] %s，等待 %.0fs 重试(%d/%d)" % (e, wait, i + 1, attempts))
                time.sleep(wait)
            except Exception as e:
                last = e
                time.sleep(self.delay * (i + 1))
        raise last if last else RuntimeError("unknown")

    # ---------- 对外主入口 ----------
    def collect(self, keywords, topic_map=None, limit=10, with_body=False, pages=1):
        """
        keywords: 关键词列表
        topic_map: {关键词: 话题方向}，未命中则用关键词本身
        limit: 每个关键词取多少条
        with_body: 是否抓正文（强反爬，建议 limit<=3）
        返回写入素材库的条数
        """
        all_items = []
        for kw in keywords:
            for page in range(1, int(pages) + 1):
                print("[collect] %s p%d" % (kw, page))
                try:
                    items = self._retry(self.search, kw, page)
                except Exception as e:
                    print("  [skip] 搜索失败：%s" % e)
                    if ("验证码" in str(e)) or ("反爬" in str(e)):
                        time.sleep(max(120, self.delay * 5))
                    continue
                items = items[:limit]
                for it in items:
                    it["topic"] = (topic_map or {}).get(kw, kw)
                # 去重（同一关键词内）
                seen, uniq = set(), []
                for it in items:
                    if it["title"] not in seen:
                        seen.add(it["title"])
                        uniq.append(it)
                all_items.extend(uniq)
                time.sleep(self._jitter())

        # 正文阶段
        if with_body:
            for it in all_items:
                try:
                    real = self._retry(self.resolve, it["sogou_link"])
                    if real:
                        it["real_url"] = real
                        art = self._retry(self.article, real)
                        it.update(art)
                        print("  [body ok] %s (%d字)" % (it["title"][:30], it.get("body_len", 0)))
                    else:
                        it["error"] = "跳转解析失败"
                except Exception as e:
                    it["error"] = str(e)
                    print("  [body fail] %s -> %s" % (it["title"][:30], e))
                time.sleep(self._jitter())

        # 只保留成功的写入；无正文时 title 就是 title
        for it in all_items:
            if it.get("real_title"):
                it["title"] = it["real_title"]
        n = db.upsert_articles(all_items)
        print("[collect] 新增 %d 条（共尝试 %d 条）" % (n, len(all_items)))
        return n


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("keywords", nargs="+")
    ap.add_argument("--topic", default="")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--with-body", action="store_true")
    ap.add_argument("--delay", type=float, default=25.0)
    ap.add_argument("--pages", type=int, default=1, help="每个关键词翻几页")
    a = ap.parse_args()
    c = Collector(a.delay)
    tmap = {k: a.topic for k in a.keywords} if a.topic else None
    c.collect(a.keywords, tmap, a.limit, a.with_body, a.pages)
    print(json.dumps(db.stats(), ensure_ascii=False))
