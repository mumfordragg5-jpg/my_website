"""
去 AI 味引擎 —— 把「写得太规整」的稿子改回人说话的样子

两层结构：

  1. 本地检测（scan，纯规则、离线、零成本）
     按 8 个维度打分，输出 0-100 的「AI 味」估值与 0-100 的「像人度」，
     并逐句标出高风险句子、命中哪些套话。不联网、不调用任何外部检测服务。

  2. 多轮重写（rewrite，需要 LLM）
     体检 → 重写 → 再体检 → 未达标就带着「这一版还剩什么问题」继续改。
     事实、数字、观点立场由 prompt 硬约束锁定，只改表达。

⚠️ 关于「朱雀」：腾讯朱雀（matrix.tencent.com/ai-detect）没有公开 API，
   本文件里的分数是**启发式估算**，方向上与 AI 检测器关注的东西一致
   （套话、句式均匀、抽象名词、缺具体细节），但**不等于朱雀的判定结果**。
   最终要拿官网页面粘一次才算数。UI 上也必须把这句话显示出来。

命令行：
    python humanizer.py --file draft.txt                 # 只体检
    python humanizer.py --file draft.txt --rewrite       # 体检 + 重写
    python humanizer.py --file draft.txt --rewrite --strength heavy --out new.txt
"""

import argparse
import io
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import db
import rewriter


# ============================================================
# 一、特征词表
# ============================================================

# (正则, 权重, 展示用标签)
CLICHES = [
    (r"综上所述", 1.8, "综上所述"), (r"总而言之", 1.8, "总而言之"),
    (r"总的来说", 1.5, "总的来说"), (r"总之", 1.2, "总之"),
    (r"值得注意的是", 1.6, "值得注意的是"), (r"需要注意的是", 1.3, "需要注意的是"),
    (r"不难发现", 1.6, "不难发现"), (r"显而易见", 1.5, "显而易见"),
    (r"毋庸置疑", 1.6, "毋庸置疑"), (r"不可否认", 1.3, "不可否认"),
    (r"从某种意义上(说|讲)", 1.4, "从某种意义上说"),
    (r"在当今社会", 1.8, "在当今社会"),
    (r"随着[^。，]{0,14}的(发展|推进|普及|提高)", 1.8, "随着……的发展"),
    (r"在[^。，]{0,10}的(背景|大潮|形势)下", 1.5, "在……的背景下"),
    (r"起到了[^。，]{0,10}的(作用|效果)", 1.5, "起到了……的作用"),
    (r"具有[^。，]{0,10}的(意义|价值)", 1.5, "具有……的意义"),
    (r"发挥着[^。，]{0,10}的作用", 1.5, "发挥着……的作用"),
    (r"意义(深远|重大)", 1.5, "意义深远"),
    (r"影响深远", 1.2, "影响深远"),
    (r"提供了有力(支撑|保障)", 1.5, "提供了有力支撑"),
    (r"奠定[^。，]{0,8}基础", 1.3, "奠定……基础"),
    (r"此外", 1.0, "此外"), (r"与此同时", 1.3, "与此同时"),
    (r"首先", 0.8, "首先"), (r"其次", 1.0, "其次"),
    (r"另一方面", 1.0, "另一方面"), (r"与此同时", 1.2, "与此同时"),
    (r"换句话说", 1.2, "换句话说"),
    (r"相信在[^。，]{0,14}下", 1.3, "相信在……下"),
    (r"让我们[^。，]{0,10}", 0.8, "让我们……"),
    (r"进一步提升", 1.0, "进一步提升"), (r"持续(推进|发力|优化)", 1.0, "持续推进"),
    (r"不断(提升|完善|加强)", 1.0, "不断提升"),
    (r"系统性(地|的)", 1.2, "系统性地"),
]

# 官腔/抽象名词（出现即“不像人说话”）
ABSTRACT_WORDS = [
    "维度", "机制", "体系", "赋能", "抓手", "闭环", "生态", "链路", "底层逻辑",
    "颗粒度", "沉淀", "复盘", "对齐", "心智", "势能", "矩阵", "范式", "路径依赖",
    "结构性", "系统性", "全方位", "多维度", "深层次", "协同", "贯通", "融通",
    "迭代", "演化", "驱动", "导向", "着力点", "落脚点", "支点", "杠杆", "顶层设计",
    "价值主张", "护城河", "破局", "颗粒", "组合拳", "方法论", "认知", "势能",
]
# 高权重抽象词（真正 AI/PPT 味的）
ABSTRACT_HEAVY = {"赋能", "抓手", "闭环", "底层逻辑", "颗粒度", "心智", "势能",
                  "矩阵", "范式", "路径依赖", "组合拳", "护城河", "顶层设计",
                  "方法论", "贯通", "融通", "着力点", "落脚点"}

PARALLEL_PATTERNS = [
    (r"不是[^。！？\n]{2,24}而是", "不是……而是……"),
    (r"不仅[^。！？\n]{2,26}(而且|还|更)", "不仅……而且……"),
    (r"既[^。！？\n]{2,18}又[^。！？\n]{2,18}", "既……又……"),
    (r"越是[^。！？\n]{2,16}越", "越是……越……"),
    (r"之所以[^。！？\n]{2,24}是因为", "之所以……是因为……"),
    (r"与其[^。！？\n]{2,20}不如", "与其……不如……"),
    (r"正是[^。！？\n]{0,10}才", "正是……才……"),
    (r"无论[^。！？\n]{2,20}都", "无论……都……"),
]

# 具体性信号 —— 越多越像人写的
RE_DIGIT = re.compile(r"\d")
RE_CN_NUM = re.compile(r"[一二三四五六七八九十百千万半两]{1,4}(块|元|岁|年|天|个月|斤|公里|人|次|成|倍)")
RE_TIME = re.compile(r"去年|前年|今年|上个月|这个月|上周|这周|昨天|前天|今天|早上|中午|晚上|"
                     r"[两三四五六七八九十]{1,2}年前|那(会|阵)儿|小时候|退休那年")
RE_PLACE = re.compile(r"[\u4e00-\u9fa5]{2,6}(市|县|区|镇|乡|村|街道|社区|医院|社保局|人社局|"
                      r"民政局|银行|学校|厂|公司|法院|派出所)")
RE_QUOTE = re.compile(r"[“\"『「][^”\"』」\n]{2,60}[”\"』」]")
RE_SELF = re.compile(r"我|咱|俺|您")
RE_ORAL = re.compile(r"说白了|讲真|老实说|其实|反正|干脆|凑合|闹心|憋屈|犯不上|不至于|"
                     r"你想|你看|你说|这事儿|那会儿|咋|啥|呗|挺|老是|八成|倒是|偏偏|"
                     r"可不是|要我说|说句|想想看")
RE_TONE = re.compile(r"[啊嘛呢吧哈呗哦喽嘞]")


# ============================================================
# 二、基础统计
# ============================================================

def _plain(t):
    """去掉 Markdown 记号，只留可分析的文字（保留换行用于分段）"""
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", t or "")
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"^[ \t]{0,3}#{1,6}[ \t]*", "", t, flags=re.M)
    t = t.replace("**", "").replace("__", "")
    t = re.sub(r"^[ \t]*>[ \t]?", "", t, flags=re.M)
    t = re.sub(r"^[ \t]*[-*+][ \t]+", "", t, flags=re.M)
    t = re.sub(r"^[ \t]*\d+[.、)][ \t]+", "", t, flags=re.M)
    t = re.sub(r"`{1,3}", "", t)
    return t.strip()


def _sentences(t):
    parts = re.split(r"(?<=[。！？!?…；;])|\n+", t)
    return [p.strip(" \t，,") for p in parts if len(p.strip(" \t，,")) >= 2]


def _paragraphs(t):
    blocks = re.split(r"\n\s*\n", t)
    if len(blocks) < 2:
        blocks = t.split("\n")
    out = []
    for b in blocks:
        b = " ".join(x.strip() for x in b.split("\n") if x.strip())
        if len(b) >= 8:
            out.append(b)
    return out


def _cv(xs):
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / len(xs)
    if m <= 0:
        return 0.0
    var = sum((x - m) ** 2 for x in xs) / len(xs)
    return math.sqrt(var) / m


def _pw(x, pts):
    """分段线性插值；pts 按 x 升序，返回 0-100"""
    if x <= pts[0][0]:
        return float(pts[0][1])
    if x >= pts[-1][0]:
        return float(pts[-1][1])
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= x <= x1:
            if x1 == x0:
                return float(y1)
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return float(pts[-1][1])


def _count(pairs, t):
    """返回 (加权命中数, 明细列表[(标签, 次数)])"""
    total = 0.0
    detail = []
    for pat, w, label in pairs:
        n = len(re.findall(pat, t))
        if n:
            total += n * w
            detail.append((label, n))
    return total, detail


def _density(n, chars, base=1000.0):
    if chars <= 0:
        return 0.0
    return n * base / chars


# ============================================================
# 三、体检
# ============================================================

DIM_NAMES = {
    "cliche":      "套话密度",
    "uniform":     "句式均匀度",
    "para":        "段落均匀度",
    "parallel":    "对仗排比",
    "abstract":    "抽象名词",
    "concrete":    "具体性（反向）",
    "punct":       "标点习惯",
    "heading":     "小标题规整度",
}

DIM_WEIGHT = {
    "cliche": 0.22, "uniform": 0.18, "para": 0.10, "parallel": 0.12,
    "abstract": 0.16, "concrete": 0.10, "punct": 0.06, "heading": 0.06,
}

ADVICE = {
    "cliche":   "删掉「综上所述 / 值得注意的是 / 不难发现 / 与此同时」这类连接词，直接说事。中文不靠这些词也能接得上。",
    "uniform":  "句子长度太接近了。插几句 5-10 字的短句（「就这么简单。」「不是钱的事。」），再把一处拆成长句。",
    "para":     "每段长度拉平了。让某一段只有一句话，另一段长一点，读起来才有呼吸感。",
    "parallel": "排比用得太多。三个以上的并列改成两个，或者把其中一个换成具体例子。",
    "abstract": "把「机制 / 体系 / 赋能 / 抓手 / 闭环」换成动作和场景：不说「完善保障机制」，说「去街道办交两张表」。",
    "concrete": "缺具体东西。补一点真实的时间、地点、金额、人物对话（只能是原文已有的事实，不许编）。",
    "punct":    "破折号、分号、引号用得偏多。人写东西没这么讲究标点。",
    "heading":  "小标题太整齐。别用「一、二、三」加对仗短语，改成一句大白话。",
}


def scan(text):
    """本地体检。返回可直接 JSON 化的报告。"""
    raw = (text or "").strip()
    t = _plain(raw)
    chars = len(re.sub(r"\s", "", t))

    empty = {
        "score": 0, "human": 100, "level": "空", "level_desc": "没有内容",
        "dims": [], "hits": {"cliche": [], "abstract": [], "sentences": []},
        "stats": {}, "advice": [], "chars": 0,
        "disclaimer": "本地启发式估算，不等于朱雀官方结果。",
    }
    if chars < 60:
        empty["level_desc"] = "内容太短（少于 60 字），判断不可靠"
        return empty

    sents = _sentences(t)
    paras = _paragraphs(t)
    lens = [len(re.sub(r"\s", "", s)) for s in sents]
    plens = [len(re.sub(r"\s", "", p)) for p in paras]
    mean_len = (sum(lens) / len(lens)) if lens else 0.0
    cv = _cv(lens)
    pcv = _cv(plens)
    short_ratio = (sum(1 for x in lens if x < 14) / len(lens)) if lens else 0.0

    dims = []

    # ---- 1. 套话 ----
    c_hits, c_detail = _count(CLICHES, t)
    d_cliche = _density(c_hits, chars)
    s_cliche = _pw(d_cliche, [(0, 5), (2, 20), (5, 45), (10, 70), (20, 90), (40, 100)])
    dims.append({
        "key": "cliche", "name": DIM_NAMES["cliche"], "score": round(s_cliche, 1),
        "detail": "每千字命中 %.1f 处套话（共 %d 处）" % (d_cliche, int(c_hits)),
    })

    # ---- 2. 句式均匀度 ----
    s_uniform = _pw(cv, [(0.28, 96), (0.40, 82), (0.50, 66), (0.62, 45), (0.78, 26), (1.00, 12)])
    if short_ratio < 0.06:
        s_uniform += 10
    elif short_ratio < 0.12:
        s_uniform += 4
    elif short_ratio >= 0.20:
        s_uniform -= 8
    if len(lens) < 8:
        s_uniform = 50.0      # 样本太少，不给强判断
    s_uniform = max(0.0, min(100.0, s_uniform))
    dims.append({
        "key": "uniform", "name": DIM_NAMES["uniform"], "score": round(s_uniform, 1),
        "detail": "句长变异系数 %.2f，短句占比 %.0f%%（%d 句）" % (cv, short_ratio * 100, len(lens)),
    })

    # ---- 3. 段落均匀度 ----
    if len(plens) >= 3:
        s_para = _pw(pcv, [(0.12, 92), (0.22, 78), (0.35, 60), (0.50, 42), (0.70, 24)])
        if all(60 <= x <= 180 for x in plens):
            s_para += 8
    else:
        s_para = 45.0
    s_para = max(0.0, min(100.0, s_para))
    dims.append({
        "key": "para", "name": DIM_NAMES["para"], "score": round(s_para, 1),
        "detail": "%d 段，段长变异系数 %.2f，最长 %d 字 / 最短 %d 字"
                  % (len(plens), pcv, max(plens) if plens else 0, min(plens) if plens else 0),
    })

    # ---- 4. 对仗排比 ----
    p_hits = 0
    p_detail = []
    for pat, label in PARALLEL_PATTERNS:
        n = len(re.findall(pat, t))
        if n:
            p_hits += n
            p_detail.append((label, n))
    # 三个逗号以上的长并列
    triple = len(re.findall(r"[^。！？\n]{6,}，[^。！？\n]{6,}，[^。！？\n]{6,}。", t))
    p_hits += triple * 1.2
    s_parallel = min(100.0, 8 + p_hits * 14)
    dims.append({
        "key": "parallel", "name": DIM_NAMES["parallel"], "score": round(s_parallel, 1),
        "detail": "命中 %d 处对仗/并列（三连并列 %d 处）" % (int(p_hits), triple),
    })

    # ---- 5. 抽象名词 ----
    ab_hit = []
    ab_score = 0.0
    for w in ABSTRACT_WORDS:
        n = t.count(w)
        if n:
            wgt = 2.0 if w in ABSTRACT_HEAVY else 1.0
            ab_score += n * wgt
            ab_hit.append({"word": w, "n": n, "heavy": w in ABSTRACT_HEAVY})
    ab_hit.sort(key=lambda x: (-x["n"], -x["heavy"]))
    d_ab = _density(ab_score, chars)
    s_abstract = _pw(d_ab, [(0, 8), (1, 22), (3, 45), (6, 68), (12, 88), (25, 100)])
    dims.append({
        "key": "abstract", "name": DIM_NAMES["abstract"], "score": round(s_abstract, 1),
        "detail": "每千字 %.1f 个（共 %d 个，其中高权重 %d 个）"
                  % (d_ab, sum(x["n"] for x in ab_hit),
                     sum(x["n"] for x in ab_hit if x["heavy"])),
    })

    # ---- 6. 具体性（反向：越具体分越低）----
    sig = 0.0
    sig += len(RE_DIGIT.findall(t)) * 1.0
    sig += len(RE_CN_NUM.findall(t)) * 1.0
    sig += len(RE_TIME.findall(t)) * 1.5
    sig += len(RE_PLACE.findall(t)) * 1.5
    sig += len(RE_QUOTE.findall(t)) * 2.0
    sig += len(RE_SELF.findall(t)) * 0.5
    sig += len(RE_ORAL.findall(t)) * 1.5
    sig += len(RE_TONE.findall(t)) * 0.8
    d_sig = _density(sig, chars)
    s_concrete = 100 - _pw(d_sig, [(0, 0), (2, 20), (5, 45), (9, 65), (15, 82), (25, 95)])
    s_concrete = max(0.0, min(100.0, s_concrete))
    dims.append({
        "key": "concrete", "name": DIM_NAMES["concrete"], "score": round(s_concrete, 1),
        "detail": "每千字 %.1f 个具体信号（数字 %d、时间 %d、地点 %d、引语 %d、口语 %d）"
                  % (d_sig, len(RE_DIGIT.findall(t)) + len(RE_CN_NUM.findall(t)),
                     len(RE_TIME.findall(t)), len(RE_PLACE.findall(t)),
                     len(RE_QUOTE.findall(t)), len(RE_ORAL.findall(t))),
    })

    # ---- 7. 标点 ----
    pn = (t.count("——") * 2.5 + t.count("；") * 0.9 + t.count("「") * 1.4
          + t.count("“") * 0.6 + t.count("、") * 0.25)
    d_pn = _density(pn, chars)
    s_punct = _pw(d_pn, [(0, 8), (3, 22), (7, 42), (14, 64), (24, 84)])
    dims.append({
        "key": "punct", "name": DIM_NAMES["punct"], "score": round(s_punct, 1),
        "detail": "每千字标点密度 %.1f（破折号 %d、分号 %d、直角引号 %d）"
                  % (d_pn, t.count("——"), t.count("；"), t.count("「")),
    })

    # ---- 8. 小标题 ----
    heads = re.findall(r"(?m)^[ \t]{0,3}(#{1,6}[ \t]*[^\n]+|[一二三四五六七八九十]{1,2}[、.][ \t]*[^\n]+)$", raw)
    s_head = 30.0
    head_note = "无小标题"
    if len(heads) >= 2:
        hlen = [len(re.sub(r"^#{1,6}[ \t]*", "", h)) for h in heads]
        hcv = _cv(hlen)
        numbered = sum(1 for h in heads if re.match(r"^[一二三四五六七八九十]{1,2}[、.]", h.strip()))
        s_head = _pw(hcv, [(0.08, 88), (0.20, 70), (0.35, 52), (0.60, 32), (1.00, 18)])
        if numbered >= 3:
            s_head += 15
        if re.search(r"写在最后|结语|总结|小结|尾声", raw):
            s_head += 10
        s_head = min(100.0, s_head)
        head_note = "%d 个小标题，长度变异系数 %.2f，编号式 %d 个" % (len(heads), hcv, numbered)
    dims.append({
        "key": "heading", "name": DIM_NAMES["heading"], "score": round(s_head, 1),
        "detail": head_note,
    })

    # ---- 汇总 ----
    total = sum(DIM_WEIGHT[d["key"]] * d["score"] for d in dims)
    total = max(0.0, min(100.0, total))
    human = round(100 - total, 1)

    if total >= 78:
        level, desc = "很高", "几乎是标准 AI 腔，检测器很容易判为生成内容"
    elif total >= 62:
        level, desc = "偏高", "结构和用词都很规整，检测器会重点关注"
    elif total >= 45:
        level, desc = "中等", "有几处明显机器痕迹，改一改能压下去"
    elif total >= 28:
        level, desc = "偏低", "读起来已经像人写的了"
    else:
        level, desc = "很低", "自然，没什么机器痕迹"

    # ---- 逐句风险 ----
    sent_rows = []
    for s in sents:
        L = len(s)
        risk = 0
        why = []
        if 18 <= L <= 46 and mean_len and abs(L - mean_len) < 0.18 * mean_len:
            risk += 26
            why.append("长度贴近全文平均")
        ch = [lb for pat, w, lb in CLICHES if re.search(pat, s)]
        if ch:
            risk += min(48, 22 * len(ch))
            why.append("套话：" + "、".join(ch[:3]))
        aw = [w for w in ABSTRACT_WORDS if w in s]
        if aw:
            risk += min(30, 11 * len(aw))
            why.append("抽象词：" + "、".join(aw[:3]))
        if not RE_DIGIT.search(s) and not RE_SELF.search(s):
            risk += 10
            why.append("无数字/人称")
        if re.match(r"^(首先|其次|此外|同时|因此|然而|另外|总之|综上|另外)", s.strip()):
            risk += 18
            why.append("套话开头")
        if s.count("，") >= 3:
            risk += 10
            why.append("逗号连缀过长")
        if len(RE_QUOTE.findall(s)) == 0 and len(s) > 40:
            risk += 6
        sent_rows.append({
            "text": s if L <= 120 else s[:120] + "…",
            "len": L, "risk": min(100, risk), "why": why,
        })
    sent_rows.sort(key=lambda x: -x["risk"])
    hot = [x for x in sent_rows if x["risk"] >= 40][:10]

    # ---- 建议 ----
    worst = sorted(dims, key=lambda d: -d["score"])[:3]
    advice = []
    for d in worst:
        if d["score"] >= 45:
            advice.append(ADVICE[d["key"]])

    return {
        "score": round(total, 1),
        "human": human,
        "level": level,
        "level_desc": desc,
        "chars": chars,
        "dims": dims,
        "hits": {
            "cliche": [{"label": k, "n": n} for k, n in c_detail],
            "abstract": ab_hit[:16],
            "sentences": hot,
        },
        "stats": {
            "chars": chars,
            "sentences": len(sents),
            "paragraphs": len(paras),
            "mean_len": round(mean_len, 1),
            "cv": round(cv, 3),
            "short_ratio": round(short_ratio, 3),
        },
        "advice": advice,
        "disclaimer": "本分数是本地启发式估算，方向上与 AI 检测器一致，但不等于腾讯朱雀的官方结果。",
    }


# ============================================================
# 四、重写
# ============================================================

HUMAN_SYSTEM = """你是一位中文母语编辑，只做一件事：把写得太"规整"的文章，改回人说话的样子。

必须遵守的硬规则：

【事实零改动】
人名、数字、日期、政策名称、机构名称、金额、比例、结论、作者的立场与判断，
一律原样保留。不许新增任何事实、案例、数据、引语。不许把确定的事写成"可能"。

【清掉机器腔】
下列表达一律不要出现：
首先 / 其次 / 此外 / 与此同时 / 综上所述 / 总而言之 / 总之 / 总的来说 /
值得注意的是 / 需要注意的是 / 不难发现 / 显而易见 / 毋庸置疑 / 不可否认 /
在当今社会 / 随着……的发展 / 在……的背景下 / 具有重要意义 / 起到了……的作用 /
为我们提供了 / 让我们 / 相信在……下 / 进一步 / 持续 / 全方位 / 多维度

【打散节奏】
句子长短必须明显交错：允许只有五六个字的短句（"就这么回事。""不是钱的事。"），
也允许一个长句连着说下去。不许每句都落在 20-35 个字之间。

【段落不齐】
段落长度要不一样：有的两三行，有的只有一句话。不要每段都用主题句开头。

【说人话】
抽象名词换成动作和场景。不写"完善保障机制"，写"去街道办交两张表"。
不用"维度 / 赋能 / 抓手 / 闭环 / 生态 / 链路 / 底层逻辑 / 颗粒度 / 心智"这类词。

【允许不完美】
可以用插入语、补充说明、反问、口语连接（说白了、其实、你想、这事儿）。
可以有一点点重复和啰嗦，人写东西本来就这样。

【结构】
小标题保留原来的信息量，但不要"一、二、三"整齐编号，也不要对仗短语；改成一句大白话。
如果原文没有小标题，就保持没有。

【结尾】
不要总结陈词。落到一件具体的事、一句提醒、或者一句反问上。

【篇幅】
与原文相当，控制在原文的 85%-115%。

【输出】
只输出文章正文本身。不要写"以下是修改后的版本"，不要解释你改了什么，
不要加任何前言、后记、标注。"""


STRENGTH = {
    "light":  ("轻", "只改词语和句子层面：删套话、换掉抽象词、调整个别句式。段落顺序和结构保持原样。改动幅度约 20%。"),
    "medium": ("中", "以重写句子为主：打散节奏、长短句交错、把抽象说法换成具体动作。段落可以合并或拆分，但顺序不乱。改动幅度约 40%。"),
    "heavy":  ("重", "在保留全部事实和逻辑顺序的前提下，重组表达方式。允许换叙述视角、换开头切入方式。改动幅度约 60%。"),
}


def _facts_block(text):
    """把原文里的数字/时间/专名抽出来，作为「不许动」的清单钉在 prompt 里"""
    nums = re.findall(r"\d+(?:\.\d+)?%?", text)
    seen, uniq = set(), []
    for n in nums:
        if n not in seen:
            seen.add(n)
            uniq.append(n)
    return uniq[:40]


def build_rewrite_prompt(text, report, strength="medium", round_no=1, prev_score=None):
    sname, sdesc = STRENGTH.get(strength, STRENGTH["medium"])
    L = []
    L.append("【这一版的做法】%s：%s" % (sname, sdesc))
    L.append("")
    L.append("【原文】")
    L.append(text.strip())
    L.append("")
    L.append("【原文里必须原样保留的数字（一个都不能改、不能少）】")
    facts = _facts_block(text)
    L.append("、".join(facts) if facts else "（原文没有明显数字，同样不许新增）")
    L.append("")

    if round_no > 1:
        L.append("【这是第 %d 轮修改】上一版被本地体检打了 %s 分的「AI 味」，还没达标。" % (round_no, prev_score))
        if report:
            worst = sorted(report.get("dims", []), key=lambda d: -d["score"])[:3]
            L.append("上一版剩下的问题：")
            for d in worst:
                if d["score"] >= 40:
                    L.append("- %s（%s）：%s" % (d["name"], d["score"], d["detail"]))
            hot = (report.get("hits", {}) or {}).get("sentences", [])[:6]
            if hot:
                L.append("上一版里最像机器的几句（要重点改掉，但意思保留）：")
                for h in hot:
                    L.append("   · %s" % h["text"])
            L.append("")
        L.append("在上一版的基础上继续改，别退回更早的表达，也别为了降分删掉内容。")
        L.append("")

    L.append("现在按上面的规则改写。只输出正文。")
    return "\n".join(L)


def rule_rewrite(text):
    """没有 LLM 时的保守降级：只做「删套话 + 拆超长句」两件事，绝不新增内容。

    效果有限（能压掉一部分套话分，但打不散句式），返回文本里会带提示。
    """
    out = text

    # 1) 句首/段首的套话连接词直接删
    for w in ("首先，", "首先,", "其次，", "其次,", "此外，", "此外,", "与此同时，",
              "另外，", "另外,", "值得注意的是，", "需要注意的是，", "不难发现，",
              "显而易见，", "毋庸置疑，", "不可否认，", "换句话说，",
              "综上所述，", "总而言之，", "总的来说，", "总之，",
              "在当今社会，", "从某种意义上说，", "从某种意义上讲，"):
        out = out.replace(w, "")

    # 2) 抽象词换成人话（只换词，不改句子结构）
    swap = {
        "底层逻辑": "底下的道理", "赋能": "帮上忙", "抓手": "办法", "闭环": "从头到尾走完",
        "颗粒度": "细到什么程度", "心智": "想法", "势能": "劲头", "矩阵": "一整套",
        "范式": "套路", "着力点": "下手的地方", "落脚点": "最后落在",
        "系统性": "整块", "全方位": "各方面", "多维度": "几个方面",
        "具有重要意义": "很要紧", "提供了有力支撑": "托住了", "奠定了坚实基础": "打了底",
    }
    for a, b in swap.items():
        out = out.replace(a, b)

    # 3) 超长句在「，而且 / ，并且 / ，同时 / ，但」处断开
    def _split(m):
        s = m.group(0)
        if len(s) < 62:
            return s
        for sep in ("，而且", "，并且", "，同时", "，但是", "，不过"):
            if sep in s:
                return s.replace(sep, "。" + sep[1:], 1)
        return s

    out = re.sub(r"[^。！？\n]{62,}[。！？]", _split, out)
    return out


def rewrite(text, title="", strength="medium", target=30, max_passes=3,
            use_llm=True, settings=None, on_pass=None):
    """
    多轮降 AI 味。
    返回 dict: {out, before, after, passes:[...], engine, warnings}
    on_pass(dict) 每轮结束回调，供界面实时展示。
    """
    src = (text or "").strip()
    if len(src) < 60:
        raise ValueError("正文太短（少于 60 字），没法判断也没法改")

    settings = settings or db.get_settings()
    before = scan(src)
    cur = src
    cur_report = before
    passes = []
    warnings = []
    engine = "rule"

    use_llm = bool(use_llm and settings.get("llm_key"))
    if not use_llm:
        warnings.append("没有配置 LLM API，只能做规则降级（删套话/拆长句），效果有限。去「设置」填 API Key 后重试。")

    for i in range(1, max(1, int(max_passes)) + 1):
        if cur_report["score"] <= target:
            break

        if use_llm:
            prompt = build_rewrite_prompt(cur, cur_report, strength, i, cur_report["score"])
            try:
                raw = rewriter.call_llm(prompt, settings, timeout=180,
                                        system=HUMAN_SYSTEM,
                                        temperature=0.92)
                cand = _tidy_output(raw, title)
                if not cand or len(cand) < len(src) * 0.55:
                    warnings.append("第 %d 轮输出过短（%d 字），已丢弃" % (i, len(cand or "")))
                    continue
                cur = cand
                engine = "llm:%s" % (settings.get("llm_model") or "")
            except Exception as e:
                warnings.append("第 %d 轮调用失败：%s" % (i, e))
                break
        else:
            cand = rule_rewrite(cur)
            if cand == cur:
                break
            cur = cand
            engine = "rule(降级)"

        cur_report = scan(cur)
        row = {
            "pass": i, "score": cur_report["score"], "human": cur_report["human"],
            "chars": len(re.sub(r"\s", "", cur)),
            "text": cur,          # 供界面在轮次之间即时预览
        }
        passes.append(row)
        if on_pass:
            try:
                on_pass(row)
            except Exception:
                pass

        if not use_llm:
            break

    after = cur_report
    if after["score"] > before["score"]:
        warnings.append("改写后反而更「像 AI」了，建议直接用原文。")
    if len(re.sub(r"\s", "", cur)) < len(re.sub(r"\s", "", src)) * 0.75:
        warnings.append("改写后篇幅明显变短（%d → %d 字），建议人工补几句。"
                        % (len(re.sub(r"\s", "", src)), len(re.sub(r"\s", "", cur))))

    return {
        "out": cur,
        "before": before,
        "after": after,
        "passes": passes,
        "engine": engine,
        "warnings": warnings,
    }


def _tidy_output(raw, title=""):
    """清掉模型爱加的前言/后记/代码块"""
    s = (raw or "").strip()
    s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    lines = s.split("\n")
    drop = re.compile(r"^(以下是|下面是|这是|修改后的|改写后的|【修改|好的[，,]|当然)")
    while lines and (not lines[0].strip() or drop.match(lines[0].strip())):
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    s = "\n".join(lines).strip()
    # 如果模型把标题也重复了一遍，去掉第一行
    if title and s.startswith(title.strip()):
        rest = s[len(title.strip()):].lstrip("\n：: ").lstrip()
        if len(rest) > 100:
            s = rest
    return s


# ============================================================
# 五、兜底：阈值判定
# ============================================================

def grade(score):
    if score >= 78:
        return "很高"
    if score >= 62:
        return "偏高"
    if score >= 45:
        return "中等"
    if score >= 28:
        return "偏低"
    return "很低"


# ============================================================
# 六、CLI
# ============================================================

def _print_report(rep, label="体检"):
    print("=" * 52)
    print("%s：AI 味 %.1f / 100（%s）—— 像人度 %.1f" % (label, rep["score"], rep["level"], rep["human"]))
    print("%s ｜ %d 字 ｜ %d 句 ｜ %d 段"
          % (rep["level_desc"], rep["chars"], rep["stats"].get("sentences", 0),
             rep["stats"].get("paragraphs", 0)))
    print("-" * 52)
    for d in rep["dims"]:
        bar = "█" * int(round(d["score"] / 5))
        print("%-8s %5.1f  %-20s %s" % (d["name"], d["score"], bar, d["detail"]))
    if rep["hits"]["cliche"]:
        print("-" * 52)
        print("套话：" + "、".join("%s×%d" % (x["label"], x["n"]) for x in rep["hits"]["cliche"]))
    if rep["hits"]["abstract"]:
        print("抽象词：" + "、".join("%s×%d" % (x["word"], x["n"]) for x in rep["hits"]["abstract"][:10]))
    if rep["hits"]["sentences"]:
        print("-" * 52)
        print("最像机器的句子：")
        for s in rep["hits"]["sentences"][:6]:
            print("  [%d] %s" % (s["risk"], s["text"][:60]))
            print("      ← %s" % "；".join(s["why"]))
    if rep["advice"]:
        print("-" * 52)
        for a in rep["advice"]:
            print("→ " + a)
    print("=" * 52)


def main():
    ap = argparse.ArgumentParser(description="去 AI 味：本地体检 + 多轮重写")
    ap.add_argument("--file", help="源文件（UTF-8）")
    ap.add_argument("--text", help="直接给正文")
    ap.add_argument("--out", help="改写结果写入的文件")
    ap.add_argument("--title", default="", help="标题（用于去掉模型重复输出的标题行）")
    ap.add_argument("--strength", default="medium", choices=["light", "medium", "heavy"])
    ap.add_argument("--target", type=float, default=30, help="目标 AI 味分数，默认 30")
    ap.add_argument("--passes", type=int, default=3, help="最多几轮")
    ap.add_argument("--rewrite", action="store_true", help="真的改写（否则只体检）")
    ap.add_argument("--rule", action="store_true", help="强制用规则降级")
    a = ap.parse_args()

    if a.file:
        with io.open(a.file, "r", encoding="utf-8") as f:
            text = f.read()
    elif a.text:
        text = a.text
    else:
        text = sys.stdin.read()

    rep = scan(text)
    _print_report(rep, "原文体检")

    if a.rewrite:
        r = rewrite(text, title=a.title, strength=a.strength, target=a.target,
                    max_passes=a.passes, use_llm=not a.rule)
        print()
        _print_report(r["after"], "改写后体检")
        print("引擎：%s ｜ 轮次：%d" % (r["engine"], len(r["passes"])))
        for w in r["warnings"]:
            print("⚠️  " + w)
        if a.out:
            with io.open(a.out, "w", encoding="utf-8") as f:
                f.write(r["out"])
            print("已写入：" + a.out)
        else:
            print("\n" + "-" * 52 + "\n" + r["out"])


if __name__ == "__main__":
    main()
