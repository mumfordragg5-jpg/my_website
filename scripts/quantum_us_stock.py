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

# 美股监控标的配置表
STOCKS_CONFIG = [
    # 宽基与高股息 ETF
    {"code": "QQQ", "name": "纳斯达克100 ETF", "category": "broad", "cat_name": "宽基与高股息 ETF", "dd_th": 0.10, "ma_th": 0.05},
    {"code": "SPY", "name": "标普500 ETF", "category": "broad", "cat_name": "宽基与高股息 ETF", "dd_th": 0.10, "ma_th": 0.05},
    {"code": "SCHD", "name": "施瓦布高股息 ETF", "category": "broad", "cat_name": "宽基与高股息 ETF", "dd_th": 0.10, "ma_th": 0.05},
    
    # 科技行业与杠杆 ETF
    {"code": "SOXX", "name": "费城半导体 ETF", "category": "sector", "cat_name": "科技行业与杠杆 ETF", "dd_th": 0.10, "ma_th": 0.05},
    {"code": "SMH", "name": "泛半导体 ETF", "category": "sector", "cat_name": "科技行业与杠杆 ETF", "dd_th": 0.10, "ma_th": 0.05},
    {"code": "VGT", "name": "信息技术 ETF", "category": "sector", "cat_name": "科技行业与杠杆 ETF", "dd_th": 0.10, "ma_th": 0.05},
    {"code": "TQQQ", "name": "纳指3倍做多 ETF", "category": "sector", "cat_name": "科技行业与杠杆 ETF", "dd_th": 0.20, "ma_th": 0.10},
    
    # 核心科技巨头
    {"code": "AAPL", "name": "苹果公司", "category": "tech", "cat_name": "核心科技巨头", "dd_th": 0.10, "ma_th": 0.05},
    {"code": "MSFT", "name": "微软", "category": "tech", "cat_name": "核心科技巨头", "dd_th": 0.10, "ma_th": 0.05},
    {"code": "GOOG", "name": "谷歌", "category": "tech", "cat_name": "核心科技巨头", "dd_th": 0.10, "ma_th": 0.05},
]

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
    
    # 1. 获取 VIX 波动率恐慌指数
    logging.info("获取 ^VIX 恐慌指数数据...")
    vix_data = get_us_data("^VIX")
    vix_price = float(vix_data["price"]) if vix_data else 0.0
    vix_chg = float(vix_data["change_pct"]) if vix_data else 0.0
    vix_is_panic = bool(vix_price >= 35.0)

    # 2. 依次获取各监控标的数据
    signals = []
    for cfg in STOCKS_CONFIG:
        code = cfg["code"]
        name = cfg["name"]
        cat = cfg["category"]
        cat_name = cfg["cat_name"]
        dd_th = cfg.get("dd_th", 0.10)
        ma_th = cfg.get("ma_th", 0.05)
        
        logging.info("正在获取 %s (%s)...", code, name)
        d = get_us_data(code)
        if not d:
            logging.warning("标的 %s 数据获取失败，跳过", code)
            continue
            
        price = float(d["price"])
        change_pct = float(d["change_pct"])
        high_52w = float(d["high_52w"])
        ma120 = float(d["ma120"]) if pd.notna(d["ma120"]) else None
        
        drawdown_pct = ((price - high_52w) / high_52w * 100) if high_52w > 0 else 0.0
        ma120_dev = ((price - ma120) / ma120 * 100) if (ma120 and ma120 > 0) else None
        
        # 买点参考计算
        buy_point_high = round(high_52w * (1 - dd_th), 2)
        buy_point_ma = round(ma120 * (1 - ma_th), 2) if ma120 else None
        
        target_candidates = [bp for bp in [buy_point_high, buy_point_ma] if bp is not None]
        target_buy_price = max(target_candidates) if target_candidates else buy_point_high
        
        gap_pct = round((price - target_buy_price) / target_buy_price * 100, 2) if target_buy_price > 0 else 0.0
        
        # 触发买入判断
        buy_reasons = []
        if price <= buy_point_high:
            buy_reasons.append(f"高点回撤≥{int(dd_th*100)}% (当前 {drawdown_pct:.1f}%)")
        if buy_point_ma and price <= buy_point_ma:
            buy_reasons.append(f"跌破MA120超{int(ma_th*100)}% (当前 {ma120_dev:.1f}%)")
            
        is_buy = len(buy_reasons) > 0
        is_near = (not is_buy) and (0 < gap_pct <= 3.0)
        
        if is_buy:
            status = "触发买入"
        elif is_near:
            status = "即将到位"
        else:
            status = "正常"

        signals.append({
            "code": code,
            "name": name,
            "category": cat,
            "cat_name": cat_name,
            "price": round(price, 2),
            "change_pct": round(change_pct, 2),
            "high_52w": round(high_52w, 2),
            "drawdown_pct": round(drawdown_pct, 2),
            "ma120": round(ma120, 2) if ma120 else None,
            "ma120_dev": round(ma120_dev, 2) if ma120_dev else None,
            "buy_point_high": buy_point_high,
            "buy_point_ma": buy_point_ma,
            "target_buy_price": target_buy_price,
            "gap_pct": gap_pct,
            "is_buy": is_buy,
            "is_near": is_near,
            "status": status,
            "buy_reasons": buy_reasons
        })

    # 3. 构造前端所需 JSON
    buy_list = [s for s in signals if s["is_buy"]]
    near_list = [s for s in signals if s["is_near"]]

    result_data = {
        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "vix": {
            "price": round(vix_price, 2),
            "change_pct": round(vix_chg, 2),
            "is_panic": vix_is_panic
        },
        "signals": {
            "buy": buy_list,
            "near": near_list,
        },
        "stocks": signals
    }
    
    # 4. 保存数据
    data_dir = website_dir / "data"
    data_dir.mkdir(exist_ok=True)
    json_file = data_dir / "us_stock_data.json"
    
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(result_data, f, ensure_ascii=False, indent=2)
    logging.info("成功保存美股数据至：%s (共 %d 只标的)", json_file, len(signals))
    
    # 记录到 history
    history_dir = data_dir / "history"
    history_dir.mkdir(exist_ok=True)
    history_file = history_dir / f"us_stock_data_{target_date}.json"
    with open(history_file, "w", encoding="utf-8") as f:
        json.dump(result_data, f, ensure_ascii=False, indent=2)
    logging.info("成功归档美股历史数据至：%s", history_file)
    
    # 5. 推送钉钉消息
    if buy_list or vix_is_panic:
        title = "🌎 触发美股抄底信号"
        content = "## 🌎 美股监控：触发抄底信号\n\n"
        
        if vix_is_panic:
            content += f"### 🚨 极度恐慌警告\n"
            content += f"- **VIX 恐慌指数**: 当前 **{vix_price:.2f}** (≥35)！市场处于极度恐慌状态，通常是美股的阶段性底部特征。\n\n"
            
        if buy_list:
            content += "### 💰 触底买入标的\n"
            for s in buy_list:
                reasons = " + ".join(s["buy_reasons"])
                content += f"- **{s['name']} ({s['code']})**: 现价 ${s['price']:.2f} | 52周高点 ${s['high_52w']:.2f} | MA120 ${s['ma120'] if s['ma120'] else 0:.2f}\n"
                content += f"  > 触发原因：{reasons}\n"
                
        if near_list:
            content += "\n### 📉 即将到位标的 (回调蓄势)\n"
            for s in near_list:
                content += f"- **{s['name']} ({s['code']})**: 现价 ${s['price']:.2f} | 目标买点 ${s['target_buy_price']:.2f} (差距 +{s['gap_pct']:.2f}%)\n"
        
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
