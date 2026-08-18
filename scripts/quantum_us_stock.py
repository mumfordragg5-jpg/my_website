import os
import sys
import json
import logging
import argparse
import pandas as pd
from pathlib import Path
from datetime import datetime
import requests

try:
    import yfinance as yf
except ImportError:
    print("Please install yfinance: pip install yfinance")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

def find_website_dir() -> Path:
    cwd = Path.cwd()
    if (cwd / "index.html").exists() and (cwd / "data").exists():
        return cwd
    parent = cwd.parent
    if (parent / "index.html").exists() and (parent / "data").exists():
        return parent
    raise FileNotFoundError("无法定位网站根目录，请确保在 my_website 目录下执行")

def send_dingtalk_msg(token: str, title: str, text: str) -> None:
    if not token:
        logging.warning("未提供 DingTalk Token，跳过消息推送")
        return
        
    url = f"https://oapi.dingtalk.com/robot/send?access_token={token}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "msgtype": "markdown",
        "markdown": {
            "title": title,
            "text": text
        }
    }
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=10)
        res_data = res.json()
        if res_data.get("errcode") == 0:
            logging.info("钉钉消息推送成功")
        else:
            logging.error("钉钉消息推送失败: %s", res_data)
    except Exception as e:
        logging.error("请求钉钉接口异常: %s", e)

def get_us_data(ticker_symbol):
    try:
        ticker = yf.Ticker(ticker_symbol)
        df = ticker.history(period="1y")
        if df.empty:
            return None
            
        df = df.dropna(subset=['Close'])
        if df.empty:
            return None
            
        current_price = df['Close'].iloc[-1]
        pre_close = df['Close'].iloc[-2] if len(df) > 1 else current_price
        change_pct = (current_price - pre_close) / pre_close * 100
        
        high_52w = df['High'].max()
        
        if len(df) >= 120:
            ma120 = df['Close'].rolling(window=120).mean().iloc[-1]
        else:
            ma120 = None
            
        return {
            "price": current_price,
            "change_pct": change_pct,
            "high_52w": high_52w,
            "ma120": ma120,
        }
    except Exception as e:
        logging.error(f"获取 {ticker_symbol} 数据失败: {e}")
        return None

def run_us_stock_analysis(target_date: str, dingtalk_token: str) -> None:
    logging.info("开始美股监控巡检 (目标日期: %s)...", target_date)

    website_dir = find_website_dir()
    
    # 获取数据
    logging.info("获取 QQQ, SPY, ^VIX 数据...")
    qqq_data = get_us_data("QQQ")
    spy_data = get_us_data("SPY")
    vix_data = get_us_data("^VIX")
    
    if not qqq_data or not spy_data or not vix_data:
        logging.error("未能获取完整的美股数据，退出。")
        return
        
    stocks = {
        "QQQ": {"name": "纳斯达克100 ETF", "data": qqq_data},
        "SPY": {"name": "标普500 ETF", "data": spy_data},
    }
    
    signals = []
    
    for code, info in stocks.items():
        d = info["data"]
        name = info["name"]
        
        buy_reasons = []
        if d["price"] <= d["high_52w"] * 0.9:
            buy_reasons.append("高点回撤≥10%")
        if d["ma120"] and d["price"] <= d["ma120"] * 0.95:
            buy_reasons.append("跌破MA120超5%")
            
        is_buy = len(buy_reasons) > 0
        
        signals.append({
            "code": code,
            "name": name,
            "price": float(d["price"]),
            "change_pct": float(d["change_pct"]),
            "high_52w": float(d["high_52w"]),
            "ma120": float(d["ma120"]) if pd.notna(d["ma120"]) else None,
            "is_buy": bool(is_buy),
            "buy_reasons": buy_reasons
        })
        
    # VIX 单独作为恐慌情绪判断
    vix_is_panic = bool(vix_data["price"] >= 35)
    
    # 构造前端所需 JSON
    result_data = {
        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "vix": {
            "price": float(vix_data["price"]),
            "change_pct": float(vix_data["change_pct"]),
            "is_panic": vix_is_panic
        },
        "stocks": signals
    }
    
    # 保存数据
    data_dir = website_dir / "data"
    data_dir.mkdir(exist_ok=True)
    json_file = data_dir / "us_stock_data.json"
    
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(result_data, f, ensure_ascii=False, indent=2)
    logging.info("成功保存美股数据至：%s", json_file)
    
    # 记录到 history
    history_dir = data_dir / "history"
    history_dir.mkdir(exist_ok=True)
    history_file = history_dir / f"us_stock_data_{target_date}.json"
    with open(history_file, "w", encoding="utf-8") as f:
        json.dump(result_data, f, ensure_ascii=False, indent=2)
    
    # 推送钉钉
    any_buy = any(s["is_buy"] for s in signals)
    
    if any_buy or vix_is_panic:
        title = "🌎 触发美股抄底信号"
        content = "## 🌎 美股监控：触发抄底信号\n\n"
        
        if vix_is_panic:
            content += f"### 🚨 极度恐慌警告\n"
            content += f"- **VIX 恐慌指数**: 当前 **{vix_data['price']:.2f}** (≥35)！市场处于极度恐慌状态，通常是美股的阶段性底部特征。\n\n"
            
        buy_stocks = [s for s in signals if s["is_buy"]]
        if buy_stocks:
            content += "### 💰 触底标的\n"
            for s in buy_stocks:
                reasons = " + ".join(s["buy_reasons"])
                content += f"- **{s['name']} ({s['code']})**: 现价 {s['price']:.2f} | 52周高点 {s['high_52w']:.2f} | MA120 {s['ma120']:.2f}\n"
                content += f"  > 触发原因：{reasons}\n"
        
        content += "\n---\n*本通知由 Quantum US Stock 策略自动生成*"
        send_dingtalk_msg(dingtalk_token, title, content)
    else:
        logging.info("未触发美股买入信号，不推送。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=str, default="", help="目标日期 YYYY-MM-DD")
    args = parser.parse_args()
    
    target_date = args.date if args.date else datetime.now().strftime("%Y-%m-%d")
    token = os.environ.get("DINGTALK_TOKEN", "")
    
    run_us_stock_analysis(target_date, token)
