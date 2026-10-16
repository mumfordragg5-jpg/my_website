# -*- coding: utf-8 -*-
"""
选题看板构建器 —— 产出可公开上站的静态数据 `data/writing-desk.json`

为什么"脱敏"：
  这个 JSON 会随网站发布到 GitHub Pages，任何人可访问。
  所以这里只输出**聚合后的结构规律**和**提炼后的选题角度**，
  绝不输出采集到的他人文章标题原文 —— 既避免版权问题，也保护你的选题策略。

看板给你看什么：
  每个方向的料量、标题公式分布、主导钩子手法、常见骨架、可切入的选题角度、写作纪律。

用法：
  python writer-station/build_board.py            # 用本地素材库重建
  python writer-station/build_board.py --keep     # 库不存在时保留已有 JSON（云端用）
"""

import argparse
import io
import json
import os
import sys
from collections import Counter
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

ROOT = os.path.dirname(BASE)
OUT = os.path.join(ROOT, "data", "writing-desk.json")

# ---------------- 标题公式的一句话解读 ----------------

FORMULA_TIPS = {
    "数字型": "用「N个 / 几条 / 几岁」把内容量化，读者一眼看到信息密度",
    "疑问型": "把读者最焦虑的问题直接当标题，制造信息缺口，逼他点开",
    "冲突型": "用强对抗词（骗局 / 纠纷 / 警惕 / 后悔）触发风险警觉",
    "悬念型": "承诺揭示「背后原因 / 真相」，用未完成感留住读者",
    "反差型": "打破常识预期（竟然 / 反而 / 比…更），制造认知落差",
    "清单型": "用「必看 / 盘点 / 一文读懂」承诺信息完整性，换收藏与转发",
    "平述型": "不加修饰，靠话题本身的刚需度吸引 —— 安全但天花板低",
}

TOPIC_TIPS = {
    "教程型": "办事流程类：怎么弄、怎么查、没到账怎么办 —— 强收藏、强转发",
    "焦虑型": "情绪疏导类：迟迟没动静、还能不能涨 —— 蹭政策悬念，情绪价值高",
    "解读型": "政策深读类：并轨、调整比例、新规 —— 建立专业感，适合做长文",
    "叙事型": "人物故事类：冲突与反转 —— 传播猛，但对原创度要求最高",
    "通用型": "泛话题型：没有明确落点，只适合做导流入口",
}

DISCIPLINE = [
    "标题锁定：标题原样保留，改写只动正文 —— 看板给出的公式用于「新写」，不是「换词」。",
    "强制增量：每篇至少补 1 个原文没有的信息点（公开政策、官方渠道、具体数字）。",
    "只借结构：借用选题角度、钩子手法、骨架顺序；不复用原句，不做同义替换式洗稿。",
    "配图白名单：只用可商用图库或自己生成，网络图片「侵删」不构成免责。",
    "低频采集：搜狗对跳转页限制严，一次 3~5 条即可，靠时间积累而非暴力抓取。",
]


def _share(n, total):
    return round(n / total, 3) if total else 0.0


def _build_angles(formulas, types, keywords):
    """把统计结果翻译成 3~6 条可直接执行的选题角度。

    刻意跳过「通用型」—— 它是分析器识别不出落点时的兜底分类，
    信息量最低，放在第一条会误导。
    """
    specific = [t for t in types if t["name"] != "通用型"]
    plain = next((t for t in types if t["name"] == "通用型"), None)

    angles = []
    if specific:
        angles.append("主打角度：「%s」—— %s" % (specific[0]["name"], specific[0]["tip"]))
    if len(specific) >= 2:
        angles.append("差异化切口：「%s」—— %s" % (specific[1]["name"], specific[1]["tip"]))
    if plain and plain.get("share", 0) >= 0.4:
        angles.append("机会点：约 %d%% 的标题以平述为主、没有明确钩子，"
                      "换成下面任一公式更容易被点开。" % round(plain["share"] * 100))
    # 首选/次选要跳过「平述型」—— 它是"没有钩子"的兜底分类，不能当推荐
    strong = [f for f in formulas if f["name"] != "平述型"]
    if strong:
        angles.append("标题公式首选「%s」：%s"
                      % (strong[0]["name"], FORMULA_TIPS.get(strong[0]["name"], "")))
    if len(strong) >= 2:
        angles.append("次选「%s」：%s"
                      % (strong[1]["name"], FORMULA_TIPS.get(strong[1]["name"], "")))
    if keywords:
        angles.append("关键词落点：%s" % "、".join(keywords[:5]))
    if not angles:
        angles.append("素材还不够，先多采集一些再来看规律。")
    return angles


def _analyze_all(arts):
    """优先读已存的分析结果；没有就现场算一遍"""
    import analyzer
    out = []
    for a in arts:
        try:
            import db
            an = db.get_analysis(a["id"])
        except Exception:
            an = None
        if not an:
            try:
                an = analyzer.analyze_article(a)
            except Exception:
                an = None
        if an:
            out.append(an)
    return out


def build_topic(topic, arts):
    import analyzer
    analyses = _analyze_all(arts)
    tpl = analyzer.aggregate_template(arts, analyses)
    total = len(analyses) or 1

    formulas = [
        {"name": n, "count": c, "share": _share(c, total),
         "tip": FORMULA_TIPS.get(n, "——")}
        for n, c in tpl.get("title_patterns", [])
    ][:6]

    types = [
        {"name": n, "count": c, "share": _share(c, total),
         "tip": TOPIC_TIPS.get(n, "——")}
        for n, c in tpl.get("topic_types", [])
    ][:5]

    hooks = [{"name": n, "count": c} for n, c in tpl.get("top_hooks", [])][:6]
    skel = [{"role": n, "count": c} for n, c in tpl.get("skeleton_roles", [])][:6]
    if not skel:
        skel = [{"role": "（暂无）", "count": 0}]
    keywords = [w for w, _ in tpl.get("top_tags", [])][:8]

    # ---- 提炼选题角度（用的是规律，不是别人的标题）----
    angles = _build_angles(formulas, types, keywords)

    return {
        "topic": topic,
        "total": len(arts),
        "with_body": sum(1 for a in arts if (a.get("body_len") or 0) > 0),
        "analyzed": len(analyses),
        "keywords": keywords,
        "formulas": formulas,
        "types": types,
        "hooks": hooks,
        "skeletons": skel,
        "angles": angles,
        "ready": len(analyses) >= 8,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true",
                    help="素材库不存在时保留已有 JSON，不覆盖")
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args()

    db_file = os.path.join(BASE, "data", "station.db")
    if not os.path.exists(db_file):
        if a.keep and os.path.exists(a.out):
            print("[board] 无本地素材库，保留已有看板：%s" % a.out)
            return 0
        print("[board] 素材库不存在：%s" % db_file)
        return 1

    import db
    db.init()

    topics = db.topics_summary()
    # 云端首次运行、或缓存被清掉时，库会是空的。
    # 这时绝不能拿"空统计"覆盖掉线上已有的看板 —— 那等于把站点页面打回空白。
    if not topics:
        if a.keep and os.path.exists(a.out):
            print("[board] 素材库为空，保留已有看板：%s" % a.out)
            return 0
        print("[board] 素材库为空，没有可统计的素材")
        return 1

    blocks, total_all, body_all = [], 0, 0
    for t in topics:
        name = t.get("topic") or "未分类"
        arts = db.list_articles(topic=name, limit=5000)
        if not arts:
            continue
        blocks.append(build_topic(name, arts))
        total_all += t.get("total") or 0
        body_all += t.get("with_body") or 0

    blocks.sort(key=lambda b: -b["total"])

    data = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "site": "科技马前卒",
        "privacy": ("本页只展示聚合后的结构规律与选题角度，"
                    "不包含任何采集到的原文标题与正文。"),
        "overview": {
            "topics": len(blocks),
            "articles": total_all,
            "with_body": body_all,
        },
        "topics": blocks,
        "discipline": DISCIPLINE,
    }

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with io.open(a.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print("[board] 已生成 %s" % a.out)
    print("[board] 方向 %d 个 · 素材 %d 条 · 带正文 %d 条"
          % (len(blocks), total_all, body_all))
    for b in blocks:
        print("   %-12s total=%-4d analyzed=%-4d ready=%s"
              % (b["topic"], b["total"], b["analyzed"], b["ready"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
