# -*- coding: utf-8 -*-
"""
微信公众号草稿箱推送

为什么单独一个模块：
  公众号接口有一堆"看起来能跑、实际会卡"的细节，集中处理掉：
    1) access_token 有 7200s 有效期，且重复获取会顶掉旧的 —— 必须本地缓存
    2) 草稿的封面(thumb_media_id)必须先上传成永久素材，不能留空
    3) 正文里的 <img> 必须是微信域名，外链图会被吞 —— 这里会检查并告警
    4) ★ IP 白名单：请求方出口 IP 必须在公众号后台白名单里。
       本机默认**强制直连**（走代理时白名单填的是节点 IP，不可控）；
       而云端 runner 的 IP 每次都在变、根本没法加白名单，
       所以额外支持 WX_PROXY —— 把请求导流到"出口固定 IP"的隧道（详见 PROXY_ENV）

依赖：仅标准库。可选 Pillow —— 装了就能在封面上渲染中文标题，没装则出纯色渐变封面。
"""

import io
import json
import os
import re
import ssl
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_CACHE = os.path.join(BASE_DIR, "data", "wx_token.json")

API = "https://api.weixin.qq.com/cgi-bin"

# ---------------- 直连（关键） ----------------
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE

# ProxyHandler({}) 显式清空代理：微信要认真实出口 IP（本机直连就是这么来的）
DIRECT = urllib.request.build_opener(
    urllib.request.ProxyHandler({}),
    urllib.request.HTTPSHandler(context=_CTX),
)

# ★ 云端例外：GitHub Actions runner 的出口 IP 每次运行都不同，无法加进白名单。
#   仓库里既有的 SSH SOCKS5 隧道（GitHub workflow 里的 ssh -D 1080）出口是**固定 IP**，
#   而且它早就在公众号白名单里了，所以云端只要设：
#       WX_PROXY=socks5h://127.0.0.1:1080
#   就等价于"用那个固定 IP 去调微信"。本机不设这个变量，行为与原来一模一样（直连）。
#   注意：socks5h 需要 PySocks（pip install pysocks）。
PROXY_ENV = "WX_PROXY"
_PROXY_OPENER = None


def use_proxy():
    """返回当前配置的代理地址；空字符串 = 直连。"""
    return (os.environ.get(PROXY_ENV) or "").strip()


def wx_opener():
    """决定微信看到的是哪个出口 IP —— 用之前先想清楚这一点。"""
    global _PROXY_OPENER
    p = use_proxy()
    if not p:
        return DIRECT
    if _PROXY_OPENER is None:
        _PROXY_OPENER = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": p, "https": p}),
            urllib.request.HTTPSHandler(context=_CTX),
        )
    return _PROXY_OPENER


class WxError(RuntimeError):
    def __init__(self, code, msg, hint=""):
        self.code, self.msg, self.hint = code, msg, hint
        super(WxError, self).__init__(
            "微信接口 %s：%s%s" % (code, msg, ("\n  提示：" + hint) if hint else ""))


ERR_HINTS = {
    40001: "access_token 无效或过期。若反复出现，检查 AppSecret 是否被重置过。",
    40007: "media_id 无效：封面素材可能被删了，或上传时 type 传错。",
    40164: "出口 IP 不在白名单。去「公众号后台 → 设置与开发 → 基本配置 → IP白名单」把这个 IP 加进去（加完等 1~2 分钟生效）。",
    41001: "缺少 access_token 参数。",
    45009: "接口调用超限：草稿/素材接口有每日与每分钟配额。",
    48001: "该接口未授权：账号类型不支持草稿箱或素材接口（需已认证的服务号/订阅号）。",
    61004: "白名单未生效，或加的不是当前出口 IP。",
    88000: "IP 白名单新增后需要 1~2 分钟生效，稍等再试。",
    -1: "系统繁忙，稍后重试（微信侧偶发）。",
}


def _http(url, data=None, method="GET", headers=None, timeout=30, opener=None,
          attempts=3):
    """发请求。网络层的偶发中断会重试；HTTP 状态错误（HTTPError）直接抛出由调用方处理。

    attempts 默认为 3：云端经 SOCKS5 隧道时偶发 "Remote end closed connection"，
    不重试就会把明明能成的推送判成失败。
    """
    h = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) WriterStation/1.0"}
    if headers:
        h.update(headers)
    last = None
    for i in range(max(1, int(attempts))):
        req = urllib.request.Request(url, data=data, headers=h, method=method)
        op = opener or wx_opener()
        try:
            return op.open(req, timeout=timeout).read()
        except urllib.error.HTTPError:
            raise
        except Exception as e:                    # noqa: BLE001
            last = e
            if i < attempts - 1:
                time.sleep(1.5 * (i + 1))
    raise last


def _api(url, data=None, method="GET", headers=None, timeout=30):
    raw = _http(url, data, method, headers, timeout).decode("utf-8", "replace")
    try:
        j = json.loads(raw)
    except Exception:
        raise WxError(-2, "返回的不是 JSON：" + raw[:200])
    code = j.get("errcode")
    if code not in (0, None):
        raise WxError(code, j.get("errmsg", ""), ERR_HINTS.get(code, ""))
    return j


# ---------------- 出口 IP 检测 ----------------

IP_SOURCES = [
    "https://myip.ipip.net",
    "https://ip.3322.net",
    "https://api.ipify.org",
    "https://ifconfig.me/ip",
]


def detect_egress_ip(use_proxy=False):
    """
    检测当前公网出口 IP。
    use_proxy=False（默认）→ 直连，也就是微信看到的那个 IP，白名单要填它。
    """
    op = urllib.request.build_opener(
        urllib.request.ProxyHandler({}) if not use_proxy else urllib.request.ProxyHandler(),
        urllib.request.HTTPSHandler(context=_CTX),
    )
    for u in IP_SOURCES:
        try:
            txt = _http(u, timeout=8, opener=op, attempts=1).decode("utf-8", "replace")
            m = re.search(r"\d{1,3}(?:\.\d{1,3}){3}", txt)
            if m:
                return m.group(0)
        except Exception:
            continue
    return ""


def detect_ip_through_configured_proxy():
    """经 WX_PROXY 出去看到的 IP —— 云端用来核对"隧道是否真的生效"。"""
    p = use_proxy()
    if not p:
        return ""
    op = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": p, "https": p}),
        urllib.request.HTTPSHandler(context=_CTX),
    )
    for u in IP_SOURCES:
        try:
            txt = _http(u, timeout=10, opener=op, attempts=1).decode("utf-8", "replace")
            m = re.search(r"\d{1,3}(?:\.\d{1,3}){3}", txt)
            if m:
                return m.group(0)
        except Exception:
            continue
    return ""


# ---------------- access_token ----------------

def _load_token_cache():
    try:
        with io.open(TOKEN_CACHE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_token_cache(d):
    os.makedirs(os.path.dirname(TOKEN_CACHE), exist_ok=True)
    with io.open(TOKEN_CACHE, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)


def get_access_token(appid, secret, force=False):
    """
    取 access_token（带本地缓存）。
    微信的 token 是「单例」：新取一个，旧的立刻失效；
    而且有频率限制，所以务必走缓存，别每次调用都去取。
    """
    if not appid or not secret:
        raise WxError(-3, "未配置 AppID / AppSecret", "到工具站「设置」页填入。")
    now = time.time()
    cache = _load_token_cache()
    if (not force
            and cache.get("appid") == appid
            and cache.get("token")
            and cache.get("expire_at", 0) - 300 > now):
        return cache["token"]

    url = ("%s/token?grant_type=client_credential&appid=%s&secret=%s"
           % (API, urllib.parse.quote(appid), urllib.parse.quote(secret)))
    j = _api(url)
    tok = j.get("access_token")
    if not tok:
        raise WxError(-4, "未返回 access_token：" + json.dumps(j, ensure_ascii=False))
    _save_token_cache({
        "appid": appid,
        "token": tok,
        "expire_at": now + int(j.get("expires_in", 7200)),
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })
    return tok


def token_status(appid):
    """不请求接口，只看本地缓存是否还有效"""
    c = _load_token_cache()
    if c.get("appid") != appid or not c.get("token"):
        return {"cached": False}
    left = int(c.get("expire_at", 0) - time.time())
    return {"cached": True, "valid": left > 0, "expires_in": left,
            "fetched_at": c.get("fetched_at", "")}


# ---------------- 封面图生成 ----------------

def _png(width, height, rows):
    """把 RGB 行数据打包成 PNG（纯标准库，8bit truecolor）"""
    raw = b"".join(b"\x00" + r for r in rows)

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


# 封面配色：暖色调，面向 50~70 岁读者
COVER_TOP = (176, 62, 58)      # 深暖红
COVER_BOTTOM = (214, 122, 74)  # 暖橙


def _cover_raw(title="", width=900, height=383):
    """无 Pillow 时的兜底：竖向渐变 + 底部浅色压边"""
    rows = []
    for y in range(height):
        t = y / float(max(1, height - 1))
        r = int(COVER_TOP[0] + (COVER_BOTTOM[0] - COVER_TOP[0]) * t)
        g = int(COVER_TOP[1] + (COVER_BOTTOM[1] - COVER_TOP[1]) * t)
        b = int(COVER_TOP[2] + (COVER_BOTTOM[2] - COVER_TOP[2]) * t)
        rows.append(bytes((r, g, b)) * width)
    return _png(width, height, rows)


def _wrap_cjk(text, font, draw, max_w, limit=3):
    """中文按字符宽度折行"""
    lines, cur = [], ""
    for ch in text:
        if ch == "\n":
            lines.append(cur)
            cur = ""
            continue
        w = draw.textlength(cur + ch, font=font)
        if w > max_w and cur:
            lines.append(cur)
            cur = ch
        else:
            cur += ch
        if len(lines) >= limit:
            break
    if cur and len(lines) < limit:
        lines.append(cur)
    if lines and len(lines) == limit:
        # 末行加省略号
        last = lines[-1]
        while last and draw.textlength(last + "…", font=font) > max_w:
            last = last[:-1]
        lines[-1] = last + ("…" if last != text else "")
    return lines


def _cover_pillow(title, width=900, height=383):
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (width, height))
    d = ImageDraw.Draw(img)
    for y in range(height):
        t = y / float(max(1, height - 1))
        d.line([(0, y), (width, y)], fill=(
            int(COVER_TOP[0] + (COVER_BOTTOM[0] - COVER_TOP[0]) * t),
            int(COVER_TOP[1] + (COVER_BOTTOM[1] - COVER_TOP[1]) * t),
            int(COVER_TOP[2] + (COVER_BOTTOM[2] - COVER_TOP[2]) * t),
        ))

    # 右上角装饰圆
    d.ellipse([width - 190, -140, width + 70, 120], fill=(255, 255, 255))
    d.ellipse([width - 150, -100, width + 30, 80], fill=None, outline=(255, 255, 255), width=2)

    def find_font(size):
        for p in (r"C:\Windows\Fonts\msyhbd.ttc", r"C:\Windows\Fonts\msyh.ttc",
                  r"C:\Windows\Fonts\simhei.ttf", r"C:\Windows\Fonts\simsun.ttc",
                  "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc"):
            if os.path.exists(p):
                try:
                    return ImageFont.truetype(p, size)
                except Exception:
                    continue
        return ImageFont.load_default()

    title = (title or "").strip()
    if title:
        size = 54 if len(title) <= 18 else (46 if len(title) <= 26 else 38)
        font = find_font(size)
        lines = _wrap_cjk(title, font, d, width - 190, limit=3)
        lh = int(size * 1.42)
        total = lh * len(lines)
        y = (height - total) // 2 - 6
        for ln in lines:
            # 阴影提升可读性
            d.text((58, y + 2), ln, font=font, fill=(120, 40, 36))
            d.text((56, y), ln, font=font, fill=(255, 255, 255))
            y += lh

    # 底部压边
    d.rectangle([0, height - 10, width, height], fill=(255, 240, 226))
    d.rectangle([0, height - 14, 190, height - 10], fill=(255, 214, 170))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def make_cover(title="", width=900, height=383):
    """生成封面 PNG 字节。优先 Pillow（能带标题），否则纯色渐变。"""
    try:
        return _cover_pillow(title, width, height)
    except Exception:
        return _cover_raw(title, width, height)


# ---------------- 素材上传 ----------------

def _multipart(fields, files, boundary=None):
    boundary = boundary or ("----WriterStationBoundary%d" % int(time.time() * 1000))
    buf = io.BytesIO()
    for k, v in (fields or {}).items():
        buf.write(("--%s\r\n" % boundary).encode())
        buf.write(('Content-Disposition: form-data; name="%s"\r\n\r\n' % k).encode())
        buf.write(str(v).encode("utf-8"))
        buf.write(b"\r\n")
    for k, (fn, data, ct) in (files or {}).items():
        buf.write(("--%s\r\n" % boundary).encode())
        buf.write(('Content-Disposition: form-data; name="%s"; filename="%s"\r\n'
                   % (k, fn)).encode())
        buf.write(("Content-Type: %s\r\n\r\n" % ct).encode())
        buf.write(data)
        buf.write(b"\r\n")
    buf.write(("--%s--\r\n" % boundary).encode())
    return buf.getvalue(), "multipart/form-data; boundary=%s" % boundary


def upload_thumb(token, png_bytes, filename="cover.png"):
    """把封面图传成永久素材（type=thumb），返回 media_id"""
    body, ct = _multipart({}, {"media": (filename, png_bytes, "image/png")})
    url = "%s/material/add_material?access_token=%s&type=thumb" % (API, token)
    j = _api(url, body, "POST", {"Content-Type": ct}, timeout=60)
    if not j.get("media_id"):
        raise WxError(-5, "上传封面未返回 media_id：" + json.dumps(j, ensure_ascii=False))
    return j


def upload_inline_image(token, data, filename="img.png"):
    """
    上传正文内的图片（不占永久素材配额），返回可用于 content 的微信域名 URL。
    注意：正文里的外链图片微信不认，必须走这一步换成自家 URL。
    """
    body, ct = _multipart({}, {"media": (filename, data, "image/png")})
    url = "%s/media/uploadimg?access_token=%s" % (API, token)
    j = _api(url, body, "POST", {"Content-Type": ct}, timeout=60)
    if not j.get("url"):
        raise WxError(-6, "上传正文图未返回 url：" + json.dumps(j, ensure_ascii=False))
    return j["url"]


# ---------------- 草稿 ----------------

MAX_DIGEST = 120


def make_digest(body_or_html, limit=MAX_DIGEST):
    """从正文里提炼摘要（去 Markdown / HTML 标记）"""
    s = re.sub(r"<[^>]+>", "", body_or_html or "")
    s = re.sub(r"^#{1,6}\s*", "", s, flags=re.M)
    s = re.sub(r"[*`>_~\-]{1,}", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > limit:
        s = s[:limit].rstrip() + "…"
    return s


def check_content(content):
    """返回正文里的潜在问题列表（外链图 / 外链文字）"""
    warns = []
    imgs = re.findall(r"<img[^>]+src=[\"']([^\"']+)[\"']", content or "", re.I)
    for src in imgs:
        if "mmbiz.qpic.cn" not in src and "mmbiz.qlogo.cn" not in src:
            warns.append("正文含非微信域名的图片，公众号会被过滤：%s" % src[:60])
    if re.search(r"<script|onclick=|javascript:", content or "", re.I):
        warns.append("正文含脚本/事件属性，公众号会清理，建议删除。")
    return warns


def add_draft(token, articles):
    """新增草稿。articles 为数组，每项含 title/content/thumb_media_id 等"""
    url = "%s/draft/add?access_token=%s" % (API, token)
    payload = json.dumps({"articles": articles}, ensure_ascii=False).encode("utf-8")
    return _api(url, payload, "POST",
                {"Content-Type": "application/json; charset=utf-8"}, timeout=60)


def build_article(title, content, thumb_media_id, author="", digest="",
                  source_url="", need_comment=0, only_fans=0):
    art = {
        "title": (title or "").strip()[:64],
        "author": (author or "").strip()[:8],
        "digest": (digest or "").strip()[:120],
        "content": content or "",
        "content_source_url": (source_url or "").strip(),
        "thumb_media_id": thumb_media_id,
        "need_open_comment": int(need_comment),
        "only_fans_can_comment": int(only_fans),
    }
    return art


# ---------------- 对外主流程 ----------------

def push_draft(appid, secret, title, content, author="", digest="",
               source_url="", cover_png=None, cover_media_id="",
               need_comment=0, only_fans=0, cover_title=None):
    """
    把一篇稿子推进草稿箱。返回 {media_id, thumb_media_id, warnings, ...}

    cover_media_id 有值则复用（不重复上传，省永久素材配额）；
    否则用 cover_png 或自动生成封面并上传。
    """
    token = get_access_token(appid, secret)
    warnings = check_content(content)

    used_cover = cover_media_id
    cover_info = {}
    if not used_cover:
        png = cover_png if cover_png else make_cover(cover_title or title)
        cover_info = upload_thumb(token, png)
        used_cover = cover_info.get("media_id", "")

    art = build_article(title, content, used_cover, author,
                        digest or make_digest(content), source_url,
                        need_comment, only_fans)
    res = add_draft(token, [art])
    return {
        "ok": True,
        "media_id": res.get("media_id", ""),
        "thumb_media_id": used_cover,
        "cover_url": cover_info.get("url", ""),
        "warnings": warnings,
        "title": art["title"],
        "digest": art["digest"],
        "engine": "wechat-draft/add",
    }


# ---------------- 账号解析：云端环境变量 ⇄ 本地设置 ----------------
#
# 与 my_website/tools 里现有的 GitHub Secrets 命名保持一致，
# 这样本机工作台和云端 Actions 用的是同一套凭据，不会出现"两套配置互相打架"。

ACCOUNT_ENV = {
    "1": {"appid": "WX_APPID", "secret": "WX_APPSECRET",
          "thumb": "WX_THUMB_MEDIA_ID", "author": "WX_AUTHOR"},
    "2": {"appid": "WX_APPID2", "secret": "WX_APPSECRET2",
          "thumb": "WX_THUMB_MEDIA_ID2", "author": "WX_AUTHOR2"},
}

ACCOUNT_DB = {
    "1": {"appid": "wx_appid", "secret": "wx_appsecret",
          "thumb": "wx_cover_media_id", "author": "wx_author"},
    "2": {"appid": "wx_appid2", "secret": "wx_appsecret2",
          "thumb": "wx_cover_media_id2", "author": "wx_author2"},
}

ACCOUNT_LABEL = {"1": "主号", "2": "副号"}

# 本机开发时，允许用 .env 覆盖（.env 已在 .gitignore 里）
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(os.path.join(BASE_DIR, ".env"))
except Exception:
    pass


def resolve_account(which="1"):
    """解析某个公众号账号的凭据。

    优先级：环境变量（云端 Actions / .env）→ 本地素材库设置（工作台界面填写）。
    返回 {"key","label","appid","secret","thumb","author","sources"}
    """
    key = "2" if str(which).strip() == "2" else "1"
    emap, dmap = ACCOUNT_ENV[key], ACCOUNT_DB[key]

    vals, sources = {}, []
    for f in ("appid", "secret", "thumb", "author"):
        v = (os.environ.get(emap[f]) or "").strip()
        if v:
            vals[f] = v
            sources.append("env:" + emap[f])

    if len(vals) < 4:
        try:
            import db as _db
            st = _db.get_settings() or {}
            for f in ("appid", "secret", "thumb", "author"):
                if f in vals:
                    continue
                v = (st.get(dmap[f]) or "").strip()
                if v:
                    vals[f] = v
                    sources.append("local:" + dmap[f])
        except Exception as e:
            sources.append("local-read-failed(%s)" % e)

    for f in ("appid", "secret", "thumb", "author"):
        vals.setdefault(f, "")

    # WS_COVER=auto → 忽略固定封面，改用自动生成的中文标题封面。
    # （固定封面通常是另一个号/另一种内容的调性，套在养老稿上会很跳）
    if (os.environ.get("WS_COVER") or "").strip().lower() == "auto":
        vals["thumb"] = ""
        sources.append("cover:auto")

    vals.update({"key": key, "label": ACCOUNT_LABEL[key], "sources": sources})
    return vals


def account_status():
    """给前端用的账号状态（不回传密钥本身）"""
    out = []
    for k in ("1", "2"):
        a = resolve_account(k)
        out.append({
            "key": k,
            "label": a["label"],
            "configured": bool(a["appid"] and a["secret"]),
            "has_thumb": bool(a["thumb"]),
            "author": a["author"],
            "sources": a["sources"],
        })
    return out


def push_draft_account(which, title, content, **kw):
    """按账号推送草稿。which 取 "1"（主号）或 "2"（副号）。

    封面策略：账号已配 thumb_media_id 就复用（省永久素材配额），
    没配就自动生成中文封面并上传。
    """
    acc = resolve_account(which)
    if not (acc["appid"] and acc["secret"]):
        raise WxError(
            "config",
            "账号「%s」未配置 AppID / AppSecret" % acc["label"],
            "本机：到工作台「设置」页填写；云端：在仓库 Secrets 里加 %s 与 %s"
            % (ACCOUNT_ENV[acc["key"]]["appid"], ACCOUNT_ENV[acc["key"]]["secret"]),
        )
    kw.setdefault("author", acc["author"])
    if not kw.get("cover_media_id"):
        kw["cover_media_id"] = acc["thumb"]
    res = push_draft(acc["appid"], acc["secret"], title, content, **kw)
    res["account"] = acc["label"]
    res["account_key"] = acc["key"]
    return res


# ---------------- 自测 ----------------

if __name__ == "__main__":
    import sys
    sys.path.insert(0, BASE_DIR)
    print("包路径 OK；直连 opener 已就绪")
    print("出口 IP（直连，也即微信看到的 IP）：", detect_egress_ip() or "检测失败")
    print("出口 IP（走代理，仅供参考）：", detect_egress_ip(use_proxy=True) or "检测失败")
    p = make_cover("养老金资格认证怎么弄？手机1分钟搞定")
    out = os.path.join(BASE_DIR, "data", "cover_sample.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "wb") as f:
        f.write(p)
    print("封面样例已生成：%s（%d 字节）" % (out, len(p)))
