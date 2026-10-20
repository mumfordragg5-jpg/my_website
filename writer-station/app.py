"""
写作工作台 —— 本地 HTTP 服务（纯标准库，无外部依赖）

启动：
    python app.py            # 默认 http://127.0.0.1:8765
    python app.py --port 9000
"""

import json
import os
import sys
import threading
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import db
import analyzer
import collector
import fetcher
import rewriter
import exporter
import wxpush
import harvest
import humanizer

WEB_DIR = os.path.join(HERE, "web")
EXPORT_DIR = os.path.join(HERE, "exports")

_job_lock = threading.Lock()
_job = {"running": False, "log": [], "kind": ""}


def job_log(msg):
    with _job_lock:
        _job["log"].append(str(msg))
        if len(_job["log"]) > 400:
            del _job["log"][:100]


def job_state():
    with _job_lock:
        return {"running": _job["running"], "kind": _job["kind"], "log": list(_job["log"])}


# ---------------- 业务动作 ----------------

def do_collect(params):
    kws = params.get("keywords") or []
    if isinstance(kws, str):
        kws = [k.strip() for k in kws.replace("，", ",").split(",") if k.strip()]
    topic = params.get("topic") or ""
    limit = int(params.get("limit") or 10)
    with_body = bool(params.get("with_body"))
    delay = float(params.get("delay") or db.get_setting("collect_delay") or 25)

    tmap = {k: topic for k in kws} if topic else None
    job_log("开始采集：%s（话题=%s，每词%d条，抓正文=%s，间隔%.0fs）"
            % ("、".join(kws), topic or "-", limit, with_body, delay))
    c = collector.Collector(delay)
    n = c.collect(kws, tmap, limit, with_body)
    job_log("采集完成，新增 %d 条" % n)
    return {"added": n}


def do_analyze_all(params):
    topic = params.get("topic")
    arts = db.list_articles(topic=topic, has_body=True, limit=500)
    n = 0
    for a in arts:
        res = analyzer.analyze_article(a)
        db.save_analysis(a["id"], res)
        n += 1
    job_log("结构分析完成：%d 篇" % n)
    return {"analyzed": n}


def do_fetch_bodies(params):
    """补正文：把列表模式下攒下来的素材逐条回填正文。

    搜狗跳转页限流极严，所以默认一次只补 3 条、间隔 30 秒，连续 3 次被拦就停。
    传 article_id 时只补那一篇（素材池行内按钮用）。
    """
    aid = int(params.get("article_id") or 0)
    todo = None
    if aid:
        a = db.get_article(aid)
        if not a:
            raise ValueError("素材不存在")
        if not a.get("sogou_link") and not a.get("real_url"):
            raise ValueError("这条没有搜狗/原站链接，补不了正文")
        if a.get("sogou_link"):
            todo = [a]
        else:
            # 已有原站链接，直接抓正文
            art = collector.Collector(0).article(a["real_url"])
            if not art.get("body"):
                raise ValueError("原站没抓到正文（可能已删除或需登录）")
            db.update_article_body(aid, art["body"], a["real_url"],
                                   art.get("real_account", ""), art.get("real_title", ""))
            job_log("正文 OK：%s（%d 字）" % ((a.get("title") or "")[:26], art["body_len"]))
            return {"ok": 1, "total": 1}

    ns = type("HarvestArgs", (), {})()
    ns.max = int(params.get("max") or 3)
    ns.topic = (params.get("topic") or "").strip()
    ns.delay = float(params.get("delay") or 30)

    orig = harvest.log

    def both(msg):
        try:
            orig(msg)          # 仍然写 data/harvest.log，留档
        except Exception:
            pass
        job_log(msg)

    harvest.log = both
    try:
        harvest.mode_body(ns, todo)
    finally:
        harvest.log = orig
    return {"ok": 1}


def do_generate(params):
    aid = int(params["article_id"])
    topic = params.get("topic")
    word_count = int(params.get("word_count") or 1200)
    use_llm = bool(params.get("use_llm"))

    inc = params.get("increments")
    if not inc:
        art = db.get_article(aid)
        kws = params.get("inc_keywords")
        if not kws:
            t = topic or (art or {}).get("topic") or ""
            kws = ["养老金 上调 政策"] if "养老" in t else ["老年人 情感需求 现状"]
        inc = fetcher.gather_increments(kws if isinstance(kws, list) else [kws], 4)

    arts_t = db.list_articles(topic=topic or (db.get_article(aid) or {}).get("topic"), has_body=True, limit=200)
    ans = [x for x in (db.get_analysis(a["id"]) for a in arts_t) if x]
    tpl = analyzer.aggregate_template(arts_t, ans) if ans else {}

    r = rewriter.generate(aid, topic=topic, template=tpl, increments=inc,
                          word_count=word_count, use_llm=use_llm)
    r.pop("prompt", None)
    job_log("已生成草稿 #%s（引擎：%s）" % (r["draft_id"], r["engine"]))
    return r


def do_export(did):
    d = db.get_draft(int(did))
    if not d:
        raise ValueError("草稿不存在")
    os.makedirs(EXPORT_DIR, exist_ok=True)
    frag = exporter.draft_to_html(d["title"], d["body"])
    page = exporter.build_page(d["title"], d["body"], "本地预览 · " + (d.get("topic") or ""))
    fp = os.path.join(EXPORT_DIR, "draft-%s.html" % did)
    with open(fp, "w", encoding="utf-8") as f:
        f.write(page)
    return {"snippet": frag, "page_path": fp}


def _run_humanize(hid, params):
    """后台跑「去 AI 味」多轮重写，过程写回 humanize 表，前端轮询即可看到进度。"""
    passes = []
    try:
        db.update_humanize(hid, status="running")
        r = humanizer.rewrite(
            params["text"],
            title=params.get("title") or "",
            strength=params.get("strength") or "medium",
            target=float(params.get("target") or 30),
            max_passes=int(params.get("max_passes") or 3),
            use_llm=bool(params.get("use_llm", True)),
            on_pass=lambda row: (passes.append(row),
                                 db.update_humanize(hid, passes=list(passes),
                                                    score_after=row["score"],
                                                    out_body=row.get("text") or "")),
        )
        db.update_humanize(
            hid,
            out_body=r["out"],
            score_before=r["before"]["score"],
            score_after=r["after"]["score"],
            scan_before=r["before"],
            scan_after=r["after"],
            passes=r["passes"],
            engine=r["engine"],
            status="done",
            error="；".join(r.get("warnings") or []),
        )
        job_log("去 AI 味完成：#%s  %.1f → %.1f（%s，%d 轮）"
                % (hid, r["before"]["score"], r["after"]["score"],
                   r["engine"], len(r["passes"])))
    except Exception as e:
        traceback.print_exc()
        db.update_humanize(hid, status="error", error=str(e))
        job_log("去 AI 味失败：#%s %s" % (hid, e))


def do_humanize_draft(params):
    """把去 AI 味的结果存成草稿，后续可编辑 / 推送草稿箱"""
    hid = int(params.get("id") or 0)
    h = db.get_humanize(hid)
    if not h:
        raise ValueError("任务不存在")
    # 界面里手改过的正文优先（否则用户改了又被库里旧版本覆盖）
    body = (params.get("out_body") or "").strip() or (h.get("out_body") or "")
    if len(body) < 60:
        raise ValueError("结果为空，先跑一次改写")
    if params.get("out_body"):
        db.update_humanize(hid, out_body=body)
    did = db.create_draft({
        "article_id": None,
        "topic": h.get("topic") or "",
        "title": h.get("title") or "（未命名）",
        "body": body,
        "outline": [],
        "increments": [],
        "source_urls": [],
        "engine": "humanize:%s" % (h.get("engine") or ""),
        "status": "draft",
    })
    return {"draft_id": did}


def do_push_draft(params):
    """把草稿推进指定公众号的草稿箱（account=1 主号 / 2 副号）"""
    did = int(params.get("draft_id") or 0)
    if not did:
        raise ValueError("缺少 draft_id")
    d = db.get_draft(did)
    if not d:
        raise ValueError("草稿不存在")
    s = db.get_settings()
    which = "2" if str(params.get("account") or "1") == "2" else "1"
    acc = wxpush.resolve_account(which)

    author = (params.get("author") or acc.get("author") or "").strip()
    cover_media_id = (params.get("cover_media_id") or acc.get("thumb") or "").strip()

    # 来源链接：auto 时回填素材原文（作为「阅读原文」），none 则留空
    source_url = ""
    if (s.get("wx_source_url") or "auto") == "auto" and d.get("article_id"):
        a = db.get_article(d["article_id"]) or {}
        source_url = a.get("real_url") or ""

    content = exporter.draft_to_html(d["title"], d["body"])

    r = wxpush.push_draft_account(
        which, d["title"], content,
        author=author, source_url=source_url, cover_media_id=cover_media_id,
        need_comment=int(s.get("wx_need_comment") or 0),
        only_fans=int(s.get("wx_only_fans") or 0),
    )
    db.update_draft(did, status="pushed",
                    wx_media_id=r.get("media_id", ""), pushed_at=db.now())
    job_log("已推送草稿 #%s 到「%s」草稿箱（media_id=%s）"
            % (did, r.get("account", ""), r.get("media_id", "")))
    r["draft_id"] = did
    return r


# ---------------- HTTP ----------------

class Handler(BaseHTTPRequestHandler):
    server_version = "WriterStation/1.0"

    def log_message(self, fmt, *args):
        pass  # 静音

    # ---- helpers ----
    # 只对 /api/stats 放开跨域：线上看板（GitHub Pages）用它探测本机服务是否在跑。
    # 其余接口一律不放开 —— 这个服务没有登录，放开等于把设置页（API Key）暴露给任意网页。
    CORS_PATHS = ("/api/stats",)
    CORS_ORIGINS = (
        "https://mumfordragg5-jpg.github.io",
        "http://127.0.0.1:8765",
        "http://localhost:8765",
    )

    def _cors_origin(self):
        if not urllib.parse.urlparse(self.path).path in self.CORS_PATHS:
            return None
        o = (self.headers.get("Origin") or "").rstrip("/")
        return o if o in self.CORS_ORIGINS else None

    def _cors_headers(self):
        o = self._cors_origin()
        if not o:
            return
        self.send_header("Access-Control-Allow-Origin", o)
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Vary", "Origin")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._cors_headers()
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def _json_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        raw = self.rfile.read(n).decode("utf-8", "replace")
        try:
            return json.loads(raw)
        except Exception:
            return {}

    def _file(self, path, ctype):
        if not os.path.exists(path):
            self._send(404, {"error": "not found"})
            return
        with open(path, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except Exception:
            pass

    # ---- routing ----
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        p, q = u.path, urllib.parse.parse_qs(u.query)
        try:
            if p in ("/", "/index.html"):
                return self._file(os.path.join(WEB_DIR, "index.html"), "text/html; charset=utf-8")
            if p.startswith("/static/"):
                fp = os.path.join(WEB_DIR, p.lstrip("/"))
                ext = os.path.splitext(fp)[1].lower()
                ct = {".css": "text/css", ".js": "application/javascript",
                      ".png": "image/png", ".svg": "image/svg+xml"}.get(ext, "text/plain")
                return self._file(fp, ct + "; charset=utf-8")

            if p == "/api/stats":
                return self._send(200, {**db.stats(), "topics": db.topics_summary()})
            if p == "/api/journal":
                return self._send(200, job_state())
            if p == "/api/articles":
                rows = db.list_articles(
                    topic=(q.get("topic") or [None])[0],
                    status=(q.get("status") or [None])[0],
                    has_body=(True if (q.get("has_body") or [""])[0] == "1"
                              else False if (q.get("has_body") or [""])[0] == "0" else None),
                    limit=int((q.get("limit") or ["200"])[0]),
                )
                if (q.get("with_analysis") or [""])[0] == "1":
                    amap = {a["article_id"]: a for a in db.all_analyses()}
                    for r in rows:
                        r["_an"] = amap.get(r["id"])
                return self._send(200, rows)
            if p.startswith("/api/articles/"):
                parts = p.strip("/").split("/")
                aid = int(parts[2])
                if len(parts) == 3:
                    a = db.get_article(aid)
                    if not a:
                        return self._send(404, {"error": "not found"})
                    a["analysis"] = db.get_analysis(aid)
                    return self._send(200, a)
                if len(parts) == 4 and parts[3] == "analysis":
                    return self._send(200, db.get_analysis(aid) or {})
            if p == "/api/template":
                topic = (q.get("topic") or [""])[0]
                arts = db.list_articles(topic=topic, has_body=True, limit=500)
                ans = [x for x in (db.get_analysis(a["id"]) for a in arts) if x]
                return self._send(200, analyzer.aggregate_template(arts, ans) if ans else {"empty": True})
            if p == "/api/drafts":
                return self._send(200, db.list_drafts())
            if p.startswith("/api/drafts/"):
                parts = p.strip("/").split("/")
                did = int(parts[2])
                if len(parts) == 3:
                    d = db.get_draft(did)
                    if not d:
                        return self._send(404, {"error": "not found"})
                    return self._send(200, d)
                if len(parts) == 4 and parts[3] in ("html", "preview"):
                    d = db.get_draft(did)
                    if not d:
                        return self._send(404, {"error": "not found"})
                    if parts[3] == "html":
                        return self._send(200, {"snippet": exporter.draft_to_html(d["title"], d["body"])})
                    return self._send(200, exporter.build_page(
                        d["title"], d["body"], "本地预览 · " + (d.get("topic") or "")),
                        "text/html; charset=utf-8")
            if p == "/api/humanize":
                return self._send(200, db.list_humanize())
            if p.startswith("/api/humanize/"):
                parts = p.strip("/").split("/")
                hid = int(parts[2])
                h = db.get_humanize(hid)
                if not h:
                    return self._send(404, {"error": "not found"})
                return self._send(200, h)
            if p == "/api/wx/status":
                s = db.get_settings()
                accounts = wxpush.account_status()
                main = wxpush.resolve_account("1")
                return self._send(200, {
                    "configured": accounts[0]["configured"],
                    "appid_masked": (main["appid"][:6] + "****" + main["appid"][-4:])
                                    if len(main["appid"]) > 10 else main["appid"],
                    "author": main["author"],
                    "cover_media_id": main["thumb"],
                    "source_url_mode": s.get("wx_source_url") or "auto",
                    "token": wxpush.token_status(main["appid"]) if main["appid"] else {"cached": False},
                    "accounts": accounts,
                })
            if p == "/api/wx/ip":
                return self._send(200, {
                    "direct": wxpush.detect_egress_ip(False),
                    "proxied": wxpush.detect_egress_ip(True),
                })
            if p == "/api/settings":
                return self._send(200, db.get_settings())

            return self._send(404, {"error": "unknown path", "path": p})
        except wxpush.WxError as e:
            return self._send(200, {"error": str(e), "code": e.code, "hint": e.hint})
        except Exception as e:
            traceback.print_exc()
            return self._send(500, {"error": str(e), "trace": traceback.format_exc()[-800:]})

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        p = u.path
        params = self._json_body()
        try:
            if p == "/api/collect":
                if _job["running"]:
                    return self._send(409, {"error": "已有任务在运行"})
                with _job_lock:
                    _job.update(running=True, kind="collect", log=[])
                t = threading.Thread(target=self._run_bg, args=(do_collect, params), daemon=True)
                t.start()
                return self._send(200, {"started": True})

            if p == "/api/analyze":
                if _job["running"]:
                    return self._send(409, {"error": "已有任务在运行"})
                with _job_lock:
                    _job.update(running=True, kind="analyze", log=[])
                t = threading.Thread(target=self._run_bg, args=(do_analyze_all, params), daemon=True)
                t.start()
                return self._send(200, {"started": True})

            if p == "/api/fetch_body":
                if _job["running"]:
                    return self._send(409, {"error": "已有任务在运行"})
                with _job_lock:
                    _job.update(running=True, kind="body", log=[])
                t = threading.Thread(target=self._run_bg, args=(do_fetch_bodies, params), daemon=True)
                t.start()
                return self._send(200, {"started": True})

            if p == "/api/generate":
                return self._send(200, do_generate(params))

            if p == "/api/increments":
                kws = params.get("keywords") or []
                if isinstance(kws, str):
                    kws = [k.strip() for k in kws.replace("，", ",").split(",") if k.strip()]
                return self._send(200, {"items": fetcher.gather_increments(kws, int(params.get("limit") or 4))})

            if p == "/api/humanize/scan":
                return self._send(200, humanizer.scan(params.get("text") or ""))

            if p == "/api/humanize/rewrite":
                text = (params.get("text") or "").strip()
                rep = humanizer.scan(text)
                if rep["chars"] < 60:
                    return self._send(200, {"error": "正文太短（少于 60 字），先贴完整的稿子",
                                            "before": rep})
                hid = db.create_humanize({
                    "title": params.get("title") or "",
                    "topic": params.get("topic") or "",
                    "src_body": text,
                    "score_before": rep["score"],
                    "scan_before": rep,
                    "strength": params.get("strength") or "medium",
                    "status": "running",
                })
                t = threading.Thread(target=_run_humanize, args=(hid, params), daemon=True)
                t.start()
                return self._send(200, {"id": hid, "before": rep})

            if p.startswith("/api/humanize/"):
                parts = p.strip("/").split("/")
                hid = int(parts[2])
                if len(parts) == 4 and parts[3] == "draft":
                    return self._send(200, do_humanize_draft({
                        "id": hid, "out_body": params.get("out_body") or ""}))

            if p.startswith("/api/drafts/"):
                parts = p.strip("/").split("/")
                did = int(parts[2])
                if len(parts) == 4 and parts[3] == "save":
                    db.update_draft(did, body=params.get("body", ""),
                                    title=params.get("title", ""),
                                    status=params.get("status", "draft"))
                    return self._send(200, {"ok": True})
                if len(parts) == 4 and parts[3] == "export":
                    return self._send(200, do_export(did))

            if p == "/api/wx/test":
                which = "2" if str(params.get("account") or "1") == "2" else "1"
                acc = dict(wxpush.resolve_account(which))
                if params.get("appid"):
                    acc["appid"] = str(params["appid"]).strip()
                if params.get("appsecret"):
                    acc["secret"] = str(params["appsecret"]).strip()
                if not (acc["appid"] and acc["secret"]):
                    return self._send(200, {
                        "error": "账号「%s」还没填 AppID / AppSecret" % acc["label"],
                        "code": -3,
                        "hint": "本机：在设置页填写；云端：在仓库 Secrets 里配置。",
                    })
                tok = wxpush.get_access_token(acc["appid"], acc["secret"], force=True)
                return self._send(200, {
                    "ok": True,
                    "account": acc["label"],
                    "token_prefix": tok[:10] + "…",
                    "egress_ip": wxpush.detect_egress_ip(False),
                    "note": "token 获取成功。若推送仍报 40164，把上面的出口 IP 加进公众号后台白名单。",
                })

            if p == "/api/wx/push":
                r = do_push_draft(params)
                if params.get("remember_cover") and r.get("thumb_media_id"):
                    key = ("wx_cover_media_id2"
                           if str(params.get("account") or "1") == "2"
                           else "wx_cover_media_id")
                    db.set_setting(key, r["thumb_media_id"])
                return self._send(200, r)

            if p == "/api/settings":
                for k, v in (params or {}).items():
                    db.set_setting(k, "" if v is None else str(v))
                return self._send(200, db.get_settings())

            return self._send(404, {"error": "unknown path", "path": p})
        except wxpush.WxError as e:
            return self._send(200, {"error": str(e), "code": e.code, "hint": e.hint})
        except Exception as e:
            traceback.print_exc()
            return self._send(500, {"error": str(e), "trace": traceback.format_exc()[-800:]})

    def do_DELETE(self):
        u = urllib.parse.urlparse(self.path)
        p = u.path
        try:
            if p.startswith("/api/humanize/"):
                db.delete_humanize(int(p.strip("/").split("/")[2]))
                return self._send(200, {"ok": True})
            if p.startswith("/api/articles/"):
                db.delete_article(int(p.strip("/").split("/")[2]))
                return self._send(200, {"ok": True})
            if p.startswith("/api/drafts/"):
                db.delete_draft(int(p.strip("/").split("/")[2]))
                return self._send(200, {"ok": True})
            return self._send(404, {"error": "unknown path"})
        except Exception as e:
            return self._send(500, {"error": str(e)})

    @staticmethod
    def _run_bg(fn, params):
        try:
            fn(params)
        except Exception as e:
            job_log("任务失败：%s" % e)
            traceback.print_exc()
        finally:
            with _job_lock:
                _job["running"] = False


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()

    db.init()
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    url = "http://%s:%d/" % (a.host, a.port)
    print("=" * 56)
    print("  公众号写作工作台")
    print("  %s" % url)
    print("  数据目录: %s" % os.path.join(HERE, "data"))
    print("  按 Ctrl+C 退出")
    print("=" * 56)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出")


if __name__ == "__main__":
    main()
