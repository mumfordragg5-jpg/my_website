#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
做T（网格波段）交易监控策略脚本
用于监控特定个股的做T低吸买入点与高抛卖出点，支持盘中实时轮询提醒与收盘数据归档。

运行模式：
  1. 单次执行模式 (GitHub Actions / 定时归档):
     python scripts/quantum_t_trade.py --once [--date 2026-09-08]
  2. 盘中实时轮询模式 (个人服务器 / 本地盘中运行):
     python scripts/quantum_t_trade.py --loop [--interval 30]
"""

import os
import sys
import time
import json
import logging
import argparse
import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
import pandas as pd

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

# ════════════════════════════════════════════════════════════════════════════
# ⚙️  做T标的配置区（用户可在此处灵活增删改做T标的及买卖价格）
# ════════════════════════════════════════════════════════════════════════════
T_STOCKS = {
    "601985": {
        "name": "中国核电",
        "buy_price": 8.50,      # 做T低吸买入参考价
        "sell_price": 9.05,     # 做T高抛卖出参考价
        "near_pct": 1.0,        # 临近预警阈值（%）
        "note": "8.50低吸接回，9.05高抛做T"
    },
    # 用户可以在这里随时添加更多个股，例如：
    # "600900": {
    #     "name": "长江电力",
    #     "buy_price": 27.50,
    #     "sell_price": 29.20,
    #     "near_pct": 1.0,
    #     "note": "波段网格做T"
    # }
}

DEFAULT_DINGTALK_TOKEN = "404c247b5758dfbd6639e8476ca9a64ccb307daeee5b219387246762cd68503d"


# ════════════════════════════════════════════════════════════════════════════
# 🌐  实时行情获取模块
# ════════════════════════════════════════════════════════════════════════════
def with_prefix(code: str) -> str:
    """根据证券代码添加交易所前缀 (sh / sz / bj)"""
    code = str(code).strip()
    if code.startswith(('60', '68', '51', '56', '58')):
        return f"sh{code}"
    elif code.startswith(('00', '30', '15', '16', '18')):
        return f"sz{code}"
    elif code.startswith(('8', '4', '92')):
        return f"bj{code}"
    return f"sh{code}"


def get_realtime_quotes(codes: List[str]) -> Dict[str, dict]:
    """批量从腾讯财经获取实时 A 股行情"""
    if not codes:
        return {}
    
    prefixed = [with_prefix(c) for c in codes]
    url = f"https://qt.gtimg.cn/q={','.join(prefixed)}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://gu.qq.com"
    }
    
    quotes = {}
    try:
        r = requests.get(url, headers=headers, timeout=8)
        if r.status_code == 200:
            lines = r.text.strip().split(';')
            for line in lines:
                line = line.strip()
                if not line or '~' not in line:
                    continue
                parts = line.split('~')
                if len(parts) > 33:
                    raw_code = parts[2]
                    name = parts[1]
                    price = float(parts[3]) if parts[3] else 0.0
                    prev_close = float(parts[4]) if parts[4] else 0.0
                    open_p = float(parts[5]) if parts[5] else 0.0
                    high_p = float(parts[33]) if parts[33] else price
                    low_p = float(parts[34]) if parts[34] else price
                    change_pct = float(parts[32]) if parts[32] else 0.0
                    
                    quotes[raw_code] = {
                        "code": raw_code,
                        "name": name,
                        "price": price,
                        "prev_close": prev_close,
                        "open": open_p,
                        "high": high_p,
                        "low": low_p,
                        "change_pct": change_pct
                    }
    except Exception as e:
        logging.warning("腾讯实时行情获取异常: %s，尝试备用新浪接口...", e)
        # 备用：新浪财经
        quotes = get_sina_quotes(codes)
        
    return quotes


def get_sina_quotes(codes: List[str]) -> Dict[str, dict]:
    """备用接口：从新浪财经获取实时行情"""
    prefixed = [with_prefix(c) for c in codes]
    url = f"https://hq.sinajs.cn/list={','.join(prefixed)}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Referer": "https://finance.sina.com.cn"
    }
    quotes = {}
    try:
        r = requests.get(url, headers=headers, timeout=8)
        if r.status_code == 200:
            for line in r.text.strip().split('\n'):
                if '="' not in line:
                    continue
                var_name, content = line.split('="')
                content = content.rstrip('";')
                parts = content.split(',')
                if len(parts) > 5:
                    raw_code = var_name.split('_')[-1][2:]
                    name = parts[0]
                    open_p = float(parts[1])
                    prev_close = float(parts[2])
                    price = float(parts[3])
                    high_p = float(parts[4])
                    low_p = float(parts[5])
                    change_pct = round((price - prev_close) / prev_close * 100, 2) if prev_close > 0 else 0.0
                    
                    quotes[raw_code] = {
                        "code": raw_code,
                        "name": name,
                        "price": price,
                        "prev_close": prev_close,
                        "open": open_p,
                        "high": high_p,
                        "low": low_p,
                        "change_pct": change_pct
                    }
    except Exception as e:
        logging.error("新浪行情获取失败: %s", e)
    return quotes


# ════════════════════════════════════════════════════════════════════════════
# 📢  钉钉消息推送模块
# ════════════════════════════════════════════════════════════════════════════
def send_dingtalk(token: str, title: str, content: str) -> bool:
    """发送钉钉机器人 Markdown 消息"""
    if not token:
        token = DEFAULT_DINGTALK_TOKEN
    
    url = f"https://oapi.dingtalk.com/robot/send?access_token={token}"
    payload = {
        "msgtype": "markdown",
        "markdown": {
            "title": title,
            "text": content
        }
    }
    
    try:
        r = requests.post(url, headers={"Content-Type": "application/json"}, json=payload, timeout=12)
        res_json = r.json()
        if res_json.get("errcode") == 0:
            logging.info("钉钉消息推送成功: %s", title)
            return True
        else:
            logging.error("钉钉推送返回错误: %s", res_json)
            return False
    except Exception as e:
        logging.error("钉钉消息推送异常: %s", e)
        return False


def build_dingtalk_message(signals: List[dict], target_date: str) -> Optional[Tuple[str, str]]:
    """构建做T预警 Markdown 消息"""
    buy_signals = [s for s in signals if s['trigger_type'] == 'BUY']
    sell_signals = [s for s in signals if s['trigger_type'] == 'SELL']
    near_buy_signals = [s for s in signals if s['trigger_type'] == 'NEAR_BUY']
    near_sell_signals = [s for s in signals if s['trigger_type'] == 'NEAR_SELL']
    
    has_triggers = bool(buy_signals or sell_signals or near_buy_signals or near_sell_signals)
    if not has_triggers:
        return None
    
    title = f"Testing {target_date} 做T网格交易预警"
    content = f"## 🎯 {title}\n> ⏳ 巡检时间：`{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`\n\n"
    
    if buy_signals:
        content += "### 🟢 触发低吸买入信号\n> 价格已跌至设定买入点，建议执行买入做T！\n\n"
        for s in buy_signals:
            chg = f"+{s['change_pct']:.2f}%" if s['change_pct'] > 0 else f"{s['change_pct']:.2f}%"
            content += (f"- **{s['name']}** ({s['code']})  \n"
                        f"  现价 **{s['price']:.2f}** ({chg}) | **买入点 {s['buy_price']:.2f}** | 偏离 `{s['gap_buy_pct']:+.2f}%`  \n"
                        f"  > 目标卖点：**{s['sell_price']:.2f}** (价差空间 `+{s['spread_pct']:.2f}%`)  \n")
        content += "\n"
        
    if sell_signals:
        content += "### 🚨 触发高抛卖出信号\n> 价格已涨至设定卖出点，建议执行高抛止盈做T！\n\n"
        for s in sell_signals:
            chg = f"+{s['change_pct']:.2f}%" if s['change_pct'] > 0 else f"{s['change_pct']:.2f}%"
            content += (f"- **{s['name']}** ({s['code']})  \n"
                        f"  现价 **{s['price']:.2f}** ({chg}) | **卖出点 {s['sell_price']:.2f}** | 偏离 `{s['gap_sell_pct']:+.2f}%`  \n"
                        f"  > 下方接回点：**{s['buy_price']:.2f}**  \n")
        content += "\n"
        
    if near_buy_signals:
        content += "### 📉 即将触达买点预警（距买点 < 1.0%）\n"
        for s in near_buy_signals:
            chg = f"+{s['change_pct']:.2f}%" if s['change_pct'] > 0 else f"{s['change_pct']:.2f}%"
            content += f"- **{s['name']}** ({s['code']}): 现价 **{s['price']:.2f}** ({chg}) | 目标买点 **{s['buy_price']:.2f}** (仅差 `{s['gap_buy_pct']:+.2f}%`)\n"
        content += "\n"

    if near_sell_signals:
        content += "### 📈 即将触达卖点预警（距卖点 < 1.0%）\n"
        for s in near_sell_signals:
            chg = f"+{s['change_pct']:.2f}%" if s['change_pct'] > 0 else f"{s['change_pct']:.2f}%"
            content += f"- **{s['name']}** ({s['code']}): 现价 **{s['price']:.2f}** ({chg}) | 目标卖点 **{s['sell_price']:.2f}** (仅差 `{s['gap_sell_pct']:+.2f}%`)\n"
        content += "\n"
        
    content += "---\n*本通知由做T网格监控策略自动触发*"
    return title, content


# ════════════════════════════════════════════════════════════════════════════
# 🚀  做T核心分析与计算
# ════════════════════════════════════════════════════════════════════════════
def run_t_trade_analysis(target_date: str, dingtalk_token: str = "") -> dict:
    """执行做T标的行情分析与状态计算"""
    codes = list(T_STOCKS.keys())
    logging.info("开始获取做T标的实时行情，共 %d 只...", len(codes))
    quotes = get_realtime_quotes(codes)
    
    items = []
    triggers = []
    
    for code, config in T_STOCKS.items():
        q = quotes.get(code, {})
        name = config.get("name", q.get("name", code))
        price = q.get("price", 0.0)
        change_pct = q.get("change_pct", 0.0)
        high = q.get("high", price)
        low = q.get("low", price)
        open_p = q.get("open", price)
        prev_close = q.get("prev_close", price)
        
        buy_price = float(config["buy_price"])
        sell_price = float(config["sell_price"])
        near_pct = float(config.get("near_pct", 1.0))
        note = config.get("note", "")
        
        # 价差空间百分比
        spread_pct = round((sell_price - buy_price) / buy_price * 100, 2) if buy_price > 0 else 0.0
        
        # 距买点偏离度（现价相对买点的差距，负数说明已经跌破买点）
        gap_buy_pct = round((price - buy_price) / buy_price * 100, 2) if buy_price > 0 else 0.0
        
        # 距卖点偏离度（现价相对卖点的差距，正数说明已经突破卖点）
        gap_sell_pct = round((price - sell_price) / sell_price * 100, 2) if sell_price > 0 else 0.0
        
        # 网格进度百分比 (0% = 在买点，100% = 在卖点)
        if sell_price > buy_price:
            grid_progress = round(((price - buy_price) / (sell_price - buy_price)) * 100, 1)
        else:
            grid_progress = 50.0
            
        # 状态判定
        status = "区间震荡"
        emoji = "⚪"
        trigger_type = "NORMAL"
        
        if price > 0:
            if price <= buy_price:
                status = "触发买入"
                emoji = "🟢"
                trigger_type = "BUY"
            elif price >= sell_price:
                status = "触发卖出"
                emoji = "🚨"
                trigger_type = "SELL"
            elif 0 < (price - buy_price) <= (buy_price * near_pct / 100):
                status = "临近买点"
                emoji = "📉"
                trigger_type = "NEAR_BUY"
            elif 0 < (sell_price - price) <= (sell_price * near_pct / 100):
                status = "临近卖点"
                emoji = "📈"
                trigger_type = "NEAR_SELL"
        
        item_data = {
            "code": code,
            "name": name,
            "price": price,
            "change_pct": change_pct,
            "high": high,
            "low": low,
            "open": open_p,
            "prev_close": prev_close,
            "buy_price": buy_price,
            "sell_price": sell_price,
            "spread_pct": spread_pct,
            "gap_buy_pct": gap_buy_pct,
            "gap_sell_pct": gap_sell_pct,
            "grid_progress": grid_progress,
            "status": status,
            "emoji": emoji,
            "trigger_type": trigger_type,
            "note": note
        }
        items.append(item_data)
        
        if trigger_type != "NORMAL":
            triggers.append(item_data)
            
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    result = {
        "update_time": now_str,
        "target_date": target_date,
        "stocks_count": len(items),
        "triggers_count": len(triggers),
        "items": items
    }
    
    # 保存数据至 data/t_trade_data.json
    base_dir = Path(__file__).resolve().parent.parent
    data_dir = base_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    history_dir = data_dir / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    
    with open(data_dir / "t_trade_data.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        
    with open(history_dir / f"t_trade_data_{target_date}.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        
    logging.info("已保存做T监控数据至: %s", data_dir / "t_trade_data.json")
    
    # 钉钉推送
    msg_res = build_dingtalk_message(triggers, target_date)
    if msg_res:
        title, content = msg_res
        send_dingtalk(dingtalk_token, title, content)
    else:
        logging.info("当前标的均在正常区间震荡，未触发买卖/临近预警。")
        
    return result


# ════════════════════════════════════════════════════════════════════════════
# 🔁  盘中循环监控模式
# ════════════════════════════════════════════════════════════════════════════
def start_loop_monitoring(interval: int = 30, dingtalk_token: str = ""):
    """盘中循环监控：每隔 interval 秒检查一次行情并在触发时提醒"""
    logging.info("启动做T盘中实时监控模式 (轮询间隔: %d 秒)...", interval)
    last_triggers = {}
    
    while True:
        try:
            now = datetime.datetime.now()
            target_date = now.strftime("%Y-%m-%d")
            
            # 判断是否在交易时间（周一至周五 09:15-11:35, 12:55-15:05）
            is_weekday = now.weekday() < 5
            hour_minute = now.hour * 100 + now.minute
            is_trading_time = is_weekday and (
                (915 <= hour_minute <= 1135) or (1255 <= hour_minute <= 1505)
            )
            
            if not is_trading_time:
                logging.info("当前非 A 股交易时间 (%s)，等待下一轮轮询...", now.strftime("%H:%M:%S"))
                time.sleep(min(interval, 60))
                continue
                
            res = run_t_trade_analysis(target_date, dingtalk_token)
            time.sleep(interval)
            
        except KeyboardInterrupt:
            logging.info("监控已手动终止。")
            break
        except Exception as e:
            logging.error("轮询异常: %s", e)
            time.sleep(10)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="做T网格交易监控策略")
    parser.add_argument("--once", action="store_true", default=True, help="单次执行分析并归档")
    parser.add_argument("--loop", action="store_true", help="盘中循环监控")
    parser.add_argument("--interval", type=int, default=30, help="循环监控间隔秒数 (默认30秒)")
    parser.add_argument("--date", type=str, default="", help="指定日期 YYYY-MM-DD")
    parser.add_argument("--webhook", type=str, default=DEFAULT_DINGTALK_TOKEN, help="自定义钉钉 Webhook Token")
    parser.add_argument("--no-publish", action="store_true", help="不自动发布")
    
    args = parser.parse_args()
    
    token = os.environ.get("DINGTALK_TOKEN", "") or args.webhook
    today_date = args.date.strip() if args.date else datetime.datetime.now().strftime("%Y-%m-%d")
    
    if args.loop:
        start_loop_monitoring(args.interval, token)
    else:
        run_t_trade_analysis(today_date, token)
