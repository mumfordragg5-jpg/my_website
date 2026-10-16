import io, json, os, ssl, urllib.request

BASE = "http://127.0.0.1:8765"
out = []


def get(p):
    try:
        r = urllib.request.urlopen(BASE + p, timeout=15)
        return r.status, r.read().decode("utf-8", "replace")
    except Exception as e:
        return None, "%s: %s" % (type(e).__name__, e)


def post(p, d):
    try:
        req = urllib.request.Request(BASE + p, data=json.dumps(d).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        r = urllib.request.urlopen(req, timeout=180)
        return r.status, r.read().decode("utf-8", "replace")
    except Exception as e:
        return None, "%s: %s" % (type(e).__name__, e)


for p in ["/api/stats", "/api/journal", "/api/settings", "/api/template?topic=%E5%85%BB%E8%80%81%E9%87%91"]:
    st, body = get(p)
    out.append("GET %s -> %s" % (p, st))
    out.append("    " + (body[:400] if body else ""))

st, body = get("/api/articles?with_analysis=1")
out.append("")
out.append("GET /api/articles -> %s  len=%s" % (st, len(body) if body else 0))
try:
    d = json.loads(body)
    out.append("    条数 %d；首条带分析: %s" % (len(d), bool(d and d[0].get("_an"))))
except Exception as e:
    out.append("    解析失败 %s | %s" % (e, (body or "")[:200]))

st, body = get("/")
out.append("")
out.append("GET / -> %s len=%s" % (st, len(body) if body else 0))

# 生成草稿（任务书模式）
st, body = post("/api/generate", {"article_id": 22, "word_count": 1100, "use_llm": False})
out.append("")
out.append("POST /api/generate -> %s" % st)
try:
    d = json.loads(body)
    out.append("    draft_id=%s engine=%s 标题=%s" % (d.get("draft_id"), d.get("engine"), (d.get("title") or "")[:40]))
    out.append("    增量条数=%d 正文字数=%d" % (len(d.get("increments") or []), len(d.get("body") or "")))
except Exception as e:
    out.append("    %s | %s" % (e, (body or "")[:400]))

# 导出
st, body = post("/api/drafts/1/export", {})
out.append("")
out.append("POST /api/drafts/1/export -> %s" % st)
try:
    d = json.loads(body)
    out.append("    snippet %d 字符 | page=%s" % (len(d.get("snippet") or ""), d.get("page_path")))
except Exception as e:
    out.append("    %s | %s" % (e, (body or "")[:300]))

# 预览页
st, body = get("/api/drafts/1/preview")
out.append("")
out.append("GET /api/drafts/1/preview -> %s len=%s" % (st, len(body) if body else 0))

io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "_api.txt"), "w", encoding="utf-8").write("\n".join(out))
print("done")
