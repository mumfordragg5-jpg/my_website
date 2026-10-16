# -*- coding: utf-8 -*-
"""
多轮低频采集 —— 把素材慢慢攒起来

实测出来的两条规律（很重要）：
  1) 搜狗「搜索页」相对宽松 —— 可以批量拉标题，这是素材的主要来源
  2) 搜狗「跳转页」限制极严 —— 连续解析几条就被验证码拦，且限流持久
     所以「补正文」只能极低频地做，且连续失败就该停手，别硬耗

因此本模块把两件事拆开：
  list  —— 批量拉标题/摘要/时间（主力，快）
  body  —— 逐条补正文（受限，能补多少算多少，连续 3 次被拦就停）

用法：
  python harvest.py --mode list
  python harvest.py --mode list --topic 养老金
  python harvest.py --mode body --max 8 --delay 30
"""

import argparse
import io
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import db          # noqa: E402
import collector   # noqa: E402

LOG = os.path.join(HERE, "data", "harvest.log")

# 两个方向的关键词池。词越具体，搜到的文章越接近目标读者。
TOPIC_KEYWORDS = {
    "养老金": [
        "养老金", "退休金", "养老金上调", "养老金资格认证", "养老保险",
    ],
    "老年人感情": [
        "黄昏恋", "老年再婚", "独居老人", "老年相亲", "空巢老人",
    ],
}

COOLDOWN = 180        # 单次触发限流后的冷却秒数
MAX_CONSEC_FAIL = 3   # 连续失败这么多次就停掉本批


def log(msg):
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
    print(line)
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with io.open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _is_rate_limit(e):
    s = str(e)
    return ("验证码" in s) or ("反爬" in s)


def mode_list(args):
    c = collector.Collector(args.delay)
    total = 0
    for topic, kws in TOPIC_KEYWORDS.items():
        if args.topic and topic != args.topic:
            continue
        for kw in kws:
            try:
                items = []
                for page in range(1, args.pages + 1):
                    items += c._retry(c.search, kw, page)
                    time.sleep(c._jitter())
            except Exception as e:
                log("搜索失败 %s：%s" % (kw, e))
                if _is_rate_limit(e):
                    log("  → 限流，冷却 %d 秒" % COOLDOWN)
                    time.sleep(COOLDOWN)
                else:
                    time.sleep(args.delay)
                continue
            dedup, seen = [], set()
            for it in items:
                if it["title"] not in seen:
                    seen.add(it["title"])
                    it["topic"] = topic
                    dedup.append(it)
            n = db.upsert_articles(dedup[:args.limit * args.pages])
            total += n
            log("%s | %s → 新增 %d" % (topic, kw, n))
            time.sleep(args.delay)
    log("★ 列表采集结束，本轮新增 %d" % total)
    log("   素材库：%s" % db.stats())


def mode_body(args):
    c = collector.Collector(args.delay)
    todo = db.articles_need_body(limit=args.max, topic=args.topic or None)
    log("★ 待补正文 %d 条" % len(todo))
    ok, consec = 0, 0
    for a in todo:
        try:
            real = c._retry(c.resolve, a["sogou_link"])
            if not real:
                log("跳转解析失败：%s" % (a["title"] or "")[:28])
                time.sleep(args.delay)
                continue
            art = c._retry(c.article, real)
            if art.get("body"):
                db.update_article_body(a["id"], art["body"], real,
                                       art.get("real_account", ""),
                                       art.get("real_title", ""))
                ok += 1
                consec = 0
                log("正文 OK：%s（%d 字）" % ((a["title"] or "")[:26], art["body_len"]))
            else:
                log("正文为空：%s" % (a["title"] or "")[:28])
        except Exception as e:
            log("失败 %s：%s" % ((a["title"] or "")[:24], e))
            if _is_rate_limit(e):
                consec += 1
                if consec >= MAX_CONSEC_FAIL:
                    log("★ 连续 %d 次被拦，本批停止。" % consec)
                    log("  搜狗跳转页限流较持久，建议隔几小时再跑，或换网络环境。")
                    break
                log("  → 冷却 %d 秒" % COOLDOWN)
                time.sleep(COOLDOWN)
                continue
        time.sleep(args.delay)
    log("★ 补正文结束，成功 %d/%d" % (ok, len(todo)))
    log("   素材库：%s" % db.stats())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["list", "body"], default="list")
    ap.add_argument("--topic", default="")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--pages", type=int, default=2)
    ap.add_argument("--max", type=int, default=8)
    ap.add_argument("--delay", type=float, default=20.0)
    a = ap.parse_args()

    db.init()
    log("=" * 52)
    log("开始：mode=%s topic=%s delay=%.0fs pages=%d"
        % (a.mode, a.topic or "全部", a.delay, a.pages))
    if a.mode == "list":
        mode_list(a)
    else:
        mode_body(a)


if __name__ == "__main__":
    main()
