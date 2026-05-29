#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
QuantumETF 钉钉实盘动量提醒机器人
==================================
功能：
  - 基于回测最优的“全仓持有多头趋势第二名”策略。
  - 每天盘后（或盘中14:50）运行，自动增量比对昨日与今日推荐标的。
  - 当推荐标的发生变化时，向钉钉机器人推送显著的【买入/卖出调仓红绿警报】。
  - 推送今日动量排行榜 TOP 5 等宽对齐数据及当前大盘多空背景。
  - 支持守护挂载循环模式（如每日 14:50 自动触发）。

依赖安装：
  pip install pandas requests mootdx

使用示例：
  # 立即执行一次并发送钉钉推送
  python quantum_etf_dingtalk.py --once
  
  # 后台常驻，每天 14:50 收盘前 10 分钟自动运行并推送
  nohup python quantum_etf_dingtalk.py --loop --run-at "14:50" > dingtalk_runner.log 2>&1 &
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Any

import pandas as pd
import requests
from mootdx.quotes import Quotes

# ────────────────────────────────────────────────────────
# 1. 默认配置与股票池
# ────────────────────────────────────────────────────────
DEFAULT_DINGTALK_WEBHOOK = "https://oapi.dingtalk.com/robot/send?access_token=404c247b5758dfbd6639e8476ca9a64ccb307daeee5b219387246762cd68503d"

DEFAULT_ETF_LIST: list[tuple[str, int]] = [
    ("510300", 1), ("510500", 1), ("510050", 1), ("588000", 1),
    ("518880", 1), ("512010", 1), ("512660", 1), ("512690", 1),
    ("512880", 1), ("515000", 1), ("159915", 0), ("159949", 0),
    ("159938", 0), ("159928", 0), ("159920", 0), ("159605", 0),
    ("515210", 1), ("512760", 1), ("515220", 1), ("515790", 1),
    ("159869", 0), ("512400", 1), ("512800", 1), # ("516120", 1),
]

ETF_NAME_MAP = {
    "510300": "沪深300 ETF", "510500": "中证500 ETF", "510050": "上证50 ETF",
    "588000": "科创50 ETF",  "518880": "黄金 ETF",     "512010": "医疗 ETF",
    "512660": "军工 ETF",     "512690": "酒 ETF",        "512880": "证券 ETF",
    "515000": "科技 ETF",     "159915": "创业板 ETF",   "159949": "创业板50 ETF",
    "159938": "全指金融 ETF", "159928": "消费 ETF",      "159920": "恒生 ETF",
    "159605": "纳斯达克100 ETF",
    "515210": "钢铁 ETF",     "512760": "半导体 ETF",   "515220": "煤炭 ETF",
    "515790": "光伏 ETF",     "159869": "游戏 ETF",     "512400": "有色 ETF",
    "512800": "银行 ETF",     # "516120": "化工 ETF",
}

MOOTDX_SERVERS = [
    ("110.41.147.114", 7709), ("8.129.13.54", 7709),
    ("120.24.149.49",  7709), ("124.70.176.52", 7709)
]


# ────────────────────────────────────────────────────────
# 2. 通达信及腾讯实时行情源
# ────────────────────────────────────────────────────────
class MootdxClient:
    def __init__(self) -> None:
        self.client = None
        self._connect()

    def _connect(self) -> None:
        for ip, port in MOOTDX_SERVERS:
            try:
                client = Quotes.factory(market="std", server=(ip, port))
                test = client.bars(symbol="510300", category=4, market=1, offset=2)
                if test is not None and not test.empty:
                    self.client = client
                    logging.info("mootdx 连通成功: %s:%d", ip, port)
                    return
            except Exception:
                pass
        logging.error("所有通达信服务器均连接失败！")

    def get_bars(self, symbol: str, market: int, bars: int = 80) -> Optional[pd.DataFrame]:
        if not self.client:
            self._connect()
        if not self.client:
            return None
        for attempt in range(3):
            try:
                df = self.client.bars(symbol=symbol, category=4, market=market, offset=bars)
                if df is not None and not df.empty:
                    if df.index.name == "datetime":
                        if "datetime" in df.columns:
                            df = df.drop(columns=["datetime"])
                        df = df.reset_index()
                    if "datetime" in df.columns:
                        df["datetime"] = pd.to_datetime(df["datetime"])
                    df = df[["datetime", "open", "close", "high", "low", "vol", "amount"]].copy()
                    for c in ["open", "close", "high", "low", "vol", "amount"]:
                        df[c] = pd.to_numeric(df[c])
                    return df.sort_values("datetime").reset_index(drop=True)
            except Exception as e:
                logging.warning("[%s] 获取K线异常: %s", symbol, e)
                time.sleep(0.5)
        return None

    def batch_get_bars(self, bars: int = 80) -> dict[str, pd.DataFrame]:
        res = {}
        for code, mkt in DEFAULT_ETF_LIST:
            df = self.get_bars(code, mkt, bars)
            if df is not None:
                res[code] = df
            time.sleep(0.05)
        return res


def tencent_quote(codes: list[str]) -> dict[str, dict]:
    url = f"https://qt.gtimg.cn/q={','.join([('sh'+c if c.startswith(('51','58')) else 'sz'+c) for c in codes])}"
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        text = r.content.decode("gbk", errors="replace")
        res = {}
        for line in text.splitlines():
            if "=" not in line:
                continue
            k, _, v = line.partition("=")
            code = k.strip().lstrip("v_")[2:]
            fields = v.strip().strip('"').split("~")
            
            def safe_float(idx: int) -> Optional[float]:
                try:
                    return float(fields[idx]) if fields[idx] not in ("", "-", "--") else None
                except Exception:
                    return None
            
            if len(fields) > 44:
                m_wan = safe_float(44)
                res[code] = {
                    "name":         fields[1],
                    "price":        safe_float(3),
                    "turnover_pct": safe_float(38),
                    "mcap_yi":      round(m_wan / 10000.0, 2) if m_wan else None
                }
        return res
    except Exception as e:
        logging.error("获取腾讯实时行情异常: %s", e)
        return {}


# ────────────────────────────────────────────────────────
# 3. 策略指标及评分大宽表计算
# ────────────────────────────────────────────────────────
def compute_scores(bars_dict: dict[str, pd.DataFrame], quotes: dict[str, dict]) -> pd.DataFrame:
    rows = []
    for code, df in bars_dict.items():
        if len(df) < 25:
            continue
            
        close = df["close"].copy()
        # 融入今日盘中实时最新价，需注意如果最后一根K线尚未更新到今日（比如刚收盘不久或盘中），应当在末尾追加今日的实时价
        q = quotes.get(code, {})
        realtime_p = q.get("price")
        if realtime_p:
            last_date = pd.to_datetime(df["datetime"].iloc[-1]).date()
            today_date = datetime.now().date()
            if last_date == today_date:
                # 最后一根 K 线已经是今天，直接更新
                close.iloc[-1] = realtime_p
            else:
                # 最后一根 K 线还是昨天，将今天的数据追加到末尾，确保均线和多天涨幅计算精度完全正确
                new_row = pd.Series([realtime_p], index=[len(close)])
                close = pd.concat([close, new_row]).reset_index(drop=True)
            
        # 计算均线
        ema20 = close.ewm(span=20, adjust=False).mean().iloc[-1]
        ema60 = close.ewm(span=60, adjust=False).mean().iloc[-1]
        
        # 偏离率
        bias = round((close.iloc[-1] / ema20 - 1) * 100, 2) if ema20 > 0 else 0.0
        
        # 涨跌幅
        def get_pct(series: pd.Series, period: int) -> float:
            if len(series) <= period:
                return 0.0
            past = series.iloc[-(period + 1)]
            return round((series.iloc[-1] / past - 1) * 100, 2) if past > 0 else 0.0
            
        pct1 = get_pct(close, 1)
        pct5 = get_pct(close, 5)
        pct10 = get_pct(close, 10)
        pct20 = get_pct(close, 20)
        
        # 5日均成交额，直接取最近 5 日的成交额均值
        recent_amt = df["amount"].tail(5).tolist()
        avg_amt_wan = (sum(recent_amt) / len(recent_amt)) / 10000.0 if recent_amt else 0.0
        
        # 过滤标准
        liquid = avg_amt_wan >= 1000.0
        trend = "多头" if ema20 > ema60 else ("空头" if ema20 < ema60 else "震荡")
        
        # Score = 0.4*bias + 0.3*pct10 + 0.3*pct20
        score = round(0.6 * bias + 0.2 * pct10 + 0.2 * pct20, 2)
        
        rows.append({
            "code": code,
            "name": ETF_NAME_MAP.get(code, code),
            "price": close.iloc[-1],
            "bias": bias,
            "pct_1": pct1,
            "pct_5": pct5,
            "pct_10": pct10,
            "pct_20": pct20,
            "score": score,
            "trend": trend,
            "liquid": liquid,
            "avg_amt_wan": avg_amt_wan
        })
        
    res_df = pd.DataFrame(rows)
    return res_df


# ────────────────────────────────────────────────────────
# 4. 对齐打印与钉钉推送
# ────────────────────────────────────────────────────────
def visual_len(s: str) -> int:
    return sum(2 if ord(char) > 127 else 1 for char in s)


def pad_string(s: str, width: int) -> str:
    v_len = visual_len(s)
    diff = width - v_len
    return s + " " * diff if diff > 0 else s


def send_dingtalk_markdown(webhook_url: str, title: str, text_content: str) -> None:
    payload = {
        "msgtype": "markdown",
        "markdown": {
            "title": title,
            "text": text_content
        },
        "at": {
            "isAtAll": False
        }
    }
    headers = {"Content-Type": "application/json; charset=utf-8"}
    try:
        r = requests.post(webhook_url, json=payload, headers=headers, timeout=15)
        r.raise_for_status()
        logging.info("钉钉消息推送成功")
    except Exception as e:
        logging.error("钉钉消息推送失败: %s", e)


# ────────────────────────────────────────────────────────
# 5. 持久化与换仓状态比对
# ────────────────────────────────────────────────────────
def find_website_dir() -> Path:
    """寻找 my_website 项目根目录，确保兼容多种执行路径"""
    # 1. 如果当前目录下有 index.html 且有 data 目录，说明当前工作目录就是 my_website
    cwd = Path(".")
    if (cwd / "index.html").exists() and (cwd / "data").exists():
        return cwd
    # 2. 如果父目录下有 index.html 且有 data 目录，说明当前是在 scripts 目录中运行
    parent = Path("..")
    if (parent / "index.html").exists() and (parent / "data").exists():
        return parent
    # 3. 指定默认的绝对路径
    abs_path = Path("d:/work_doc/python_project/my_website")
    if abs_path.exists():
        return abs_path
    # 4. 默认的相对路径
    return Path("../my_website")


STATE_FILE = Path("last_state.json")


def load_last_target(website_dir: Optional[Path] = None) -> Optional[str]:
    """读取上一次的目标持仓代码"""
    # 1. 优先从网站的 data/etf_data.json 读取，这在 GitHub Actions 等无状态环境下非常有用
    if website_dir:
        json_file = website_dir / "data" / "etf_data.json"
        if json_file.exists():
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    val = data.get("today_target", {}).get("code")
                    if val:
                        logging.info("从现有 etf_data.json 成功读取历史持仓: %s", val)
                        return val
            except Exception as e:
                logging.warning("读取 etf_data.json 历史状态失败: %s", e)

    # 2. 备用：从本地临时状态文件读取
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                val = data.get("target_code")
                if val:
                    logging.info("从 last_state.json 成功读取历史持仓: %s", val)
                    return val
        except Exception:
            pass
    return None


def save_current_target(code: Optional[str]) -> None:
    """写入当前的目标持仓代码"""
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"target_code": code, "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}, f)
    except Exception as e:
        logging.error("保存昨日状态失败: %s", e)


# ────────────────────────────────────────────────────────

# 6. 分析与推送控制中心
# ────────────────────────────────────────────────────────
def save_and_publish_etf_data(scores_df: pd.DataFrame, today_target_code: Optional[str], today_target_name: Optional[str], today_target_price: Optional[float], last_target_code: Optional[str], signal_title: str, signal_desc: str, no_publish: bool) -> None:
    """保存行情及选股评分数据为静态 JSON，并推送到 GitHub 网站仓库"""
    try:
        # 1. 拼装 ETF 行情大排行榜数据
        all_etfs = []
        # 按分数降序排列
        sorted_df = scores_df.sort_values(by="score", ascending=False).reset_index(drop=True)
        for idx, r in sorted_df.iterrows():
            code = r["code"]
            is_target = (code == today_target_code)
            is_filtered = not (r["liquid"] and r["trend"] == "多头")
            all_etfs.append({
                "rank": idx + 1,
                "code": code,
                "name": r["name"],
                "price": float(r["price"]),
                "bias": float(r["bias"]),
                "pct_1": float(r["pct_1"]),
                "pct_5": float(r["pct_5"]),
                "pct_10": float(r["pct_10"]),
                "pct_20": float(r["pct_20"]),
                "score": float(r["score"]),
                "trend": r["trend"],
                "liquid": bool(r["liquid"]),
                "avg_amt_wan": float(r["avg_amt_wan"]),
                "is_filtered": is_filtered,
                "is_target": is_target
            })
            
        # 2. 拼装完整 JSON 结构
        data_json = {
            "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "today_target": {
                "code": today_target_code,
                "name": today_target_name,
                "price": float(today_target_price) if today_target_price else None,
                "action": signal_title,
                "signal_desc": signal_desc
            },
            "last_target_code": last_target_code,
            "backtest_stats": {
                "total_return": "+514.47%",
                "annual_return": "+28.03%",
                "max_drawdown": "-27.91%",
                "sharpe_ratio": "0.85"
            },
            "all_etfs": all_etfs
        }
        
        # 3. 确定写入的物理路径
        website_dir = find_website_dir()
            
        if not website_dir.exists():
            logging.warning("未找到 my_website 项目文件夹，跳过 JSON 数据输出与发布。")
            return
            
        data_dir = website_dir / "data"
        data_dir.mkdir(exist_ok=True)
        json_file = data_dir / "etf_data.json"
        
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(data_json, f, ensure_ascii=False, indent=2)
        logging.info("成功输出静态数据至：%s", json_file)
        
        # 4. 执行 Git 自动提交推送逻辑
        if no_publish:
            logging.info("启用 --no-publish，跳过 GitHub 自动推送流程。")
            return
            
        import subprocess
        logging.info("开始执行 Git 自动推送流程...")
        
        # 依次运行 git 命令
        # git add data/etf_data.json
        subprocess.run(["git", "-C", str(website_dir), "add", "data/etf_data.json"], check=True)
        
        # 检查是否有文件改动，若无改动则不提交
        status_res = subprocess.run(["git", "-C", str(website_dir), "status", "--porcelain"], capture_output=True, text=True)
        if not status_res.stdout.strip():
            logging.info("数据无改动，跳过 Git 提交与推送。")
            return
            
        commit_msg = f"auto: update etf data {datetime.now().strftime('%Y-%m-%d')}"
        subprocess.run(["git", "-C", str(website_dir), "commit", "-m", commit_msg], check=True)
        
        # 推送到远程 GitHub
        subprocess.run(["git", "-C", str(website_dir), "push"], check=True)
        logging.info("GitHub 自动推送成功！数据已更新发布。")
        
    except Exception as e:
        logging.error("保存或发布 ETF 数据时发生错误: %s", e)


def run_analysis_and_notify(webhook_url: str, no_publish: bool = False) -> None:
    logging.info("开始执行 QuantumETF 动量选股分析...")
    
    # 1. 抓取 K 线
    client = MootdxClient()
    bars_dict = client.batch_get_bars(80)
    if not bars_dict:
        logging.error("行情源为空，终止分析")
        return
        
    # 2. 抓取实时行情
    codes = list(bars_dict.keys())
    quotes = tencent_quote(codes)
    
    # 3. 计算策略大宽表
    scores_df = compute_scores(bars_dict, quotes)
    if scores_df.empty:
        logging.error("指标计算结果为空，终止")
        return
        
    # 4. 执行策略过滤与排序
    # 硬性筛选条件：成交额 >= 1000万 且 必须是多头趋势
    filtered_df = scores_df[(scores_df["liquid"] == True) & (scores_df["trend"] == "多头")].copy()
    filtered_df = filtered_df.sort_values(by="score", ascending=False).reset_index(drop=True)
    
    # 5. 提取今日目标：Skip 1 Top 1 (即排行榜第 2 名)
    today_target_code = None
    today_target_name = None
    today_target_price = None
    
    if len(filtered_df) >= 2:
        # 足够 2 个候选，选择第二名
        target_row = filtered_df.iloc[1]
        today_target_code = target_row["code"]
        today_target_name = target_row["name"]
        today_target_price = target_row["price"]
    elif len(filtered_df) == 1:
        # 如果备选池只有 1 个，根据回测 Skip 1 则无票可选，建议空仓
        logging.warning("今日候选池仅有 1 只，由于设定跳过第 1 名，今日无票可选，策略将空仓。")
    else:
        # 如果备选池无票，全仓空仓
        logging.warning("今日候选池无满足多头趋势的标的，策略将全仓空仓。")
        
    # 6. 读取昨日状态，判断是否触发【调仓换股信号】
    website_dir = find_website_dir()
    last_target_code = load_last_target(website_dir if website_dir.exists() else None)
    
    signal_title = "持仓保持"
    signal_desc = "📈 今日暂无调仓指令，**继续持有**原标的。"
    
    if last_target_code != today_target_code:
        # 发生了换仓
        signal_title = "调仓警报"
        
        # 细分四种情况
        if last_target_code is not None and today_target_code is not None:
            # 换仓
            last_name = ETF_NAME_MAP.get(last_target_code, last_target_code)
            signal_desc = (
                f"🚨 **【调仓警报】** 动量第一顺位发生更替！\n"
                f"👉 请在今日收盘前 **全仓卖出** 原持仓：`{last_name} ({last_target_code})`\n"
                f"👉 随后以收盘价 **等额买入** 新标的：`{today_target_name} ({today_target_code})`"
            )
        elif last_target_code is None and today_target_code is not None:
            # 空仓开仓
            signal_desc = (
                f"🟢 **【买入开仓】** 大盘回暖，动量选股触发开仓信号！\n"
                f"👉 请以收盘价 **买入开仓**：`{today_target_name} ({today_target_code})`"
            )
        elif last_target_code is not None and today_target_code is None:
            # 仓位出局变现
            last_name = ETF_NAME_MAP.get(last_target_code, last_target_code)
            signal_desc = (
                f"🔴 **【全仓平仓】** 市场行情转入弱势，无多头标的符合要求！\n"
                f"👉 请在今日收盘前 **全部卖出变现** 原持仓：`{last_name} ({last_target_code})`，**保留现金，空仓避险**。"
            )
        else:
            # 连续空仓
            signal_desc = "❄️ **【持续空仓】** 市场全线弱势，无任何满足多头趋势的标的。**请继续保留现金观望**。"
            
    # 7. 保存今日状态
    save_current_target(today_target_code)
    
    # 8. 生成排行榜 Markdown 文本
    # 过滤出符合条件的标的，展示有效的多头候选池排行榜，使“持有第二名”的视觉排名更直观
    all_sorted = scores_df.sort_values(by="score", ascending=False).reset_index(drop=True)
    
    # 找出被过滤掉的高评分标的（排在有效多头第一名之前的被过滤排除标的）
    filtered_out_high_scores = []
    first_valid_score = filtered_df.iloc[0]["score"] if not filtered_df.empty else -999.0
    for idx, r in all_sorted.iterrows():
        if r["score"] > first_valid_score:
            if not (r["liquid"] and r["trend"] == "多头"):
                reason = "流动性不足" if not r["liquid"] else "空头趋势"
                filtered_out_high_scores.append(f"`{r['name']} ({r['code']})` ({r['score']:.2f}分, 因{reason}被排除)")
        else:
            break
            
    # 排行榜只展示符合条件的有效多头趋势标的前 5 名
    top_5 = filtered_df.head(5)
    
    # 构建等宽文本表格
    header = "排名 代码   名称          现价  偏离率  10日%  评分  趋势\n"
    divider = "─" * 58 + "\n"
    rows = []
    
    for idx, r in top_5.iterrows():
        rank = str(idx + 1)
        code = str(r["code"])
        name = pad_string(str(r["name"]), 12)
        price = f"{r['price']:.3f}"
        bias = f"{r['bias']:+.2f}"
        pct10 = f"{r['pct_10']:+.2f}"
        score = f"{r['score']:+.2f}"
        
        # 趋势特殊标注
        trend_icon = "▲" if r["trend"] == "多头" else ("▼" if r["trend"] == "空头" else "─")
        
        # 如果是策略选中的那只（第二名），在表格前面加星号高亮
        is_target = "★" if code == today_target_code else " "
        
        row_line = f"{is_target}{rank:<2} {code} {name} {price:>5} {bias:>5} {pct10:>5} {score:>5}  {trend_icon}\n"
        rows.append(row_line)
        
    table_text = header + divider + "".join(rows) if rows else "(今日无满足多头趋势的标的)\n"
    
    # 高分排除备注
    filter_note = ""
    if filtered_out_high_scores:
        filter_note = "\n⚠️ **今日高分排除**：\n" + "\n".join([f"- {x}" for x in filtered_out_high_scores]) + "\n"
        
    # 9. 构建发送给钉钉的最终 Markdown 消息
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    target_display = f"`{today_target_name} ({today_target_code})`" if today_target_code else "⚠️ **今日空仓避险**"
    
    markdown_msg = (
        f"Quantum\n"
        f"> ⏳ 分析时间：`{now_str}`\n"
        f"> 🎯 今日目标：{target_display}\n\n"
        f"--- \n"
        f"### 🔔 信号决策：**【{signal_title}】**\n"
        f"{signal_desc}\n\n"
        f"--- \n"
        f"### 📈 今日多头动量排行榜 (★表策略选中)\n"
        f"```text\n"
        f"{table_text}"
        f"```\n"
        f"{filter_note}"
        f"【策略规则】：只持有多头趋势 (`EMA20 > EMA60`) 的 **第二名**。第一名超买严重，予以跳过。\n"
    )
    
    # 10. 发送推送
    send_dingtalk_markdown(webhook_url, f"QuantumETF {signal_title}", markdown_msg)
    
    # 11. 保存并发布 JSON 数据到网站
    save_and_publish_etf_data(
        scores_df, 
        today_target_code, 
        today_target_name, 
        today_target_price, 
        last_target_code, 
        signal_title, 
        signal_desc, 
        no_publish
    )


# ────────────────────────────────────────────────────────
# 7. 运行主逻辑与定时
# ────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="QuantumETF 钉钉实盘调仓机器人")
    parser.add_argument("--once", action="store_true", help="立即运行一次并推送，随后退出")
    parser.add_argument("--loop", action="store_true", help="以守护进程模式运行，每日指定时间自动触发")
    parser.add_argument("--run-at", default="14:50", help="每日触发的时间 (建议收盘前 10 分钟如 14:50)")
    parser.add_argument("--webhook", default=DEFAULT_DINGTALK_WEBHOOK, help="自定义钉钉 Webhook 接口")
    parser.add_argument("--no-publish", action="store_true", help="跳过 GitHub 自动推送流程")
    
    args = parser.parse_args()
    
    # 创建日志文件夹
    Path("logs").mkdir(exist_ok=True)
    
    # 配置日志
    log_format = "%(asctime)s [%(levelname)s] %(message)s"
    logging.basicConfig(level=logging.INFO, format=log_format, handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/quantum_etf_dingtalk.log", encoding="utf-8")
    ])
    
    # 重配置 stdout 编码，防止 Windows 中文乱码
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
        
    if not args.once and not args.loop:
        # 默认一次性执行退出
        args.once = True
        
    if args.once:
        logging.info("触发 --once 选项，启动分析并推送...")
        run_analysis_and_notify(args.webhook, no_publish=args.no_publish)
        logging.info("执行完毕，正常退出。")
        sys.exit(0)
        
    if args.loop:
        trigger_times = [t.strip() for t in args.run_at.split(",")]
        logging.info("已启动守护模式。每日触发时间：%s", trigger_times)
        
        last_ran_date = {}
        while True:
            try:
                now = datetime.now()
                now_time_str = now.strftime("%H:%M")
                now_date_str = now.strftime("%Y-%m-%d")
                
                # 检查当前时间是否达到触发设置
                for trigger_time in trigger_times:
                    if now_time_str == trigger_time:
                        if last_ran_date.get(trigger_time) != now_date_str:
                            logging.info("达到设定的定时任务触发时间：%s，开始分析...", trigger_time)
                            run_analysis_and_notify(args.webhook, no_publish=args.no_publish)
                            last_ran_date[trigger_time] = now_date_str
                            logging.info("定时推送完毕。")
                            
                time.sleep(30)
            except KeyboardInterrupt:
                logging.info("已手动中止。")
                break
            except Exception as e:
                logging.error("守护模式抛出异常，30秒后重试：%s", e)
                time.sleep(30)


if __name__ == "__main__":
    # python scripts/quantum_etf_dingtalk.py --once --no-publish
    main()
