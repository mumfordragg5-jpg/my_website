#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
白马股 MA120 均值回归策略监控脚本
==================================
功能：
  - 基于横盘震荡型、趋势成长型和长期持有型的白马股池进行 MA120 均值回归监控。
  - 自动输出静态数据 JSON 并推送到静态网站。
  - 支持历史日期回溯计算与归档生成。
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import re
import sys
import time
import urllib.request
import warnings
from pathlib import Path
from typing import Dict, List, Optional, Any

import pandas as pd
import requests

warnings.filterwarnings('ignore', category=DeprecationWarning)

# ════════════════════════════════════════════════════════════════════════════
# ⚙️  配置区
# ════════════════════════════════════════════════════════════════════════════

DEFAULT_DINGTALK_TOKEN = "404c247b5758dfbd6639e8476ca9a64ccb307daeee5b219387246762cd68503d"

# ── 股票池：按操作策略分三类 ─────────────────────────────────────────────

RANGE_STOCKS = {
    '600000': '浦发银行', '600015': '华夏银行', '000001': '平安银行', '600008': '上港集团',
    '600269': '赣粤高速', '000429': '粤高速A',  '001965': '招商公路',
    '601006': '大秦铁路', '600377': '宁沪高速', '601166': '兴业银行',
    '000651': '格力电器', '600023': '浙能电力', '601668': '中国建筑',
    '600741': '华域汽车', '600970': '中材国际', '600958': '东方证券',
    '300059': '东方财富', '600570': '恒生电子',
}

TREND_STOCKS = {
    '000858': '五粮液',   '603369': '今世缘',  '603198': '迎驾贡酒',
    '600690': '海尔智家', '000921': '海信家电', '002415': '海康威视',
    '600660': '福耀玻璃', '600887': '伊利股份', '000333': '美的集团',
    '600177': '雅戈尔',
}

HOLD_STOCKS = {
    '601225': '陕西煤业', '601088': '中国神华', '600938': '中国海油',
    '600900': '长江电力', '600036': '招商银行', '601939': '建设银行',
    '601398': '工商银行', '601288': '农业银行', '600519': '贵州茅台',
    '601318': '中国平安', '601328': '交通银行', '600941': '中国移动',
    '601728': '中国电信', '601919': '中远海控', '601857': '中国石油',
    '600028': '中国石化', '600350': '山东高速',
}

MA_WINDOW   = 120
BUY_RATIO1  = 0.88
BUY_RATIO2  = 0.78
RANGE_SELL  = 1.12
NEAR_PCT    = 3.0
HISTORY_DAYS = 400

_UA = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/124.0.0.0 Safari/537.36'
)

# 腾讯字段映射与数值转换
TENCENT_FIELDS = {
    1: 'name', 3: 'price', 4: 'last_close', 5: 'open',
    9: 'bid1', 10: 'bid1_vol', 11: 'bid2', 12: 'bid2_vol',
    31: 'change_amt', 32: 'change_pct', 33: 'high', 34: 'low',
    37: 'amount_wan', 38: 'turnover_pct', 39: 'pe_ttm',
    44: 'mcap_yi', 46: 'pb',
}
TENCENT_NUMERIC = {'price', 'last_close', 'open', 'high', 'low', 'change_amt', 'change_pct', 'amount_wan', 'pe_ttm', 'mcap_yi', 'pb'}


# ════════════════════════════════════════════════════════════════════════════
# 🔧  基础工具函数
# ════════════════════════════════════════════════════════════════════════════

def normalize_code(code: str) -> str:
    return re.sub(r'^(sh|sz|bj)', '', code.strip().lower()).zfill(6)

def get_market_prefix(code: str) -> str:
    c = normalize_code(code)
    if c.startswith(('6', '9')): return 'sh'
    if c.startswith('8'):        return 'bj'
    return 'sz'

def with_prefix(code: str) -> str:
    c = normalize_code(code)
    return get_market_prefix(c) + c

def get_market_id(code: str) -> int:
    return 1 if get_market_prefix(code) in ('sh', 'bj') else 0

def _safe_float(val) -> float | None:
    if val is None or str(val).strip() in ('', '--', '-', 'null', 'None'):
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None

def _safe_val(val, default=0.0) -> float:
    res = _safe_float(val)
    return res if res is not None else default


# ════════════════════════════════════════════════════════════════════════════
# 📡  数据源 Layer 1 — 腾讯财经
# ════════════════════════════════════════════════════════════════════════════

def get_tencent_quote(codes: List[str]) -> pd.DataFrame:
    prefixed = [with_prefix(c) for c in codes]
    url = f'https://qt.gtimg.cn/q={",".join(prefixed)}'
    try:
        req = urllib.request.Request(url)
        req.add_header('User-Agent', _UA)
        resp = urllib.request.urlopen(req, timeout=10)
        text = resp.read().decode('gbk')
    except Exception as e:
        logging.warning(f'腾讯财经实时行情请求失败: {e}')
        return pd.DataFrame()

    rows = []
    for line in text.strip().split(';'):
        line = line.strip()
        if not line or '=' not in line or '"' not in line:
            continue
        m = re.match(r'v_(\w+)="([^"]*)"', line)
        if not m:
            continue
        symbol_key = m.group(1)
        vals = m.group(2).split('~')
        if len(vals) < 47:
            continue
        row = {'code': symbol_key[2:]}
        for idx, col in TENCENT_FIELDS.items():
            if idx < len(vals):
                raw = vals[idx]
                row[col] = _safe_float(raw) if col in TENCENT_NUMERIC else raw
        rows.append(row)

    return pd.DataFrame(rows) if rows else pd.DataFrame()


# ════════════════════════════════════════════════════════════════════════════
# 📡  数据源 Layer 2 — mootdx
# ════════════════════════════════════════════════════════════════════════════

class MootdxClient:
    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            try:
                from mootdx import config
                original_get = config.get
                def patched_get(key, *args, **kwargs):
                    val = original_get(key, *args, **kwargs)
                    if key == 'BESTIP' and isinstance(val, dict):
                        return {k: v for k, v in val.items() if v}
                    return val
                config.get = patched_get
            except Exception:
                pass
            from mootdx.quotes import Quotes
            self._client = Quotes.factory(market='std', multithread=True, heartbeat=True)
            logging.info('mootdx 连通成功')
        return self._client

    def get_kline(self, code: str, count: int = 250) -> pd.DataFrame:
        code = normalize_code(code)
        market = get_market_id(code)
        try:
            df = self.client.bars(symbol=code, category=4, market=market, start=0, offset=count)
            if df is not None and not df.empty:
                df = df.reset_index()
                if "datetime" in df.columns:
                    df["date"] = pd.to_datetime(df["datetime"])
                return df
        except Exception as e:
            logging.warning(f'mootdx get_kline({code}) 失败: {e}')
        return pd.DataFrame()

    def get_realtime(self, codes: List[str]) -> pd.DataFrame:
        norm = [normalize_code(c) for c in codes]
        try:
            raw = self.client.quotes(norm)
            if raw is not None and not raw.empty:
                df = pd.DataFrame(raw)
                if 'code' not in df.columns:
                    df.insert(0, 'code', norm[:len(df)])
                return df
        except Exception as e:
            logging.warning(f'mootdx get_realtime 失败: {e}')
        return pd.DataFrame()

    def close(self):
        if self._client is not None:
            try:
                self._client.client.close()
            except Exception:
                pass
            self._client = None


# ════════════════════════════════════════════════════════════════════════════
# 📡  数据源 Layer 3 — 百度股市通日K线
# ════════════════════════════════════════════════════════════════════════════

def get_baidu_kline(code: str) -> pd.DataFrame:
    code_norm = normalize_code(code)
    params = {
        'all': '1', 'isIndex': 'false', 'isBk': 'false', 'isBlock': 'false',
        'isFutures': 'false', 'isStock': 'true', 'newFormat': '1',
        'group': 'quotation_kline_ab', 'finClientType': 'pc',
        'code': code_norm, 'ktype': '1',
    }
    headers = {
        'User-Agent': _UA,
        'Accept': 'application/vnd.finance-web.v1+json',
        'Origin': 'https://gushitong.baidu.com',
        'Referer': 'https://gushitong.baidu.com/',
    }
    url = 'https://finance.pae.baidu.com/selfselect/getstockquotation'
    try:
        r = requests.get(url, headers=headers, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        result = data.get('Result', {})
        md = result.get('newMarketData', {})
        keys = md.get('keys', [])
        raw_rows = md.get('marketData', '')
        if not keys or not raw_rows:
            return pd.DataFrame()

        rows = []
        for line in raw_rows.split(';'):
            line = line.strip()
            if not line:
                continue
            vals = line.split(',')
            if len(vals) == len(keys):
                rows.append({k: v for k, v in zip(keys, vals)})

        if rows:
            df = pd.DataFrame(rows)
            df = df.rename(columns={'time': 'date'})
            for col in ['open', 'close', 'high', 'low', 'volume']:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
            df['date'] = pd.to_datetime(df['date'])
            return df.sort_values('date').reset_index(drop=True)
    except Exception as e:
        logging.warning(f'百度K线获取失败({code_norm}): {e}')
    return pd.DataFrame()


# ════════════════════════════════════════════════════════════════════════════
# 📡  综合实时行情抓取 (多源容灾)
# ════════════════════════════════════════════════════════════════════════════

def get_realtime_quotes(stock_codes: List[str], mootdx: Optional[MootdxClient] = None) -> Dict[str, Dict]:
    result = {}
    if not stock_codes:
        return result

    # 1. 腾讯财经
    try:
        df_tx = get_tencent_quote(stock_codes)
        if not df_tx.empty:
            for _, r in df_tx.iterrows():
                code = normalize_code(str(r.get('code', '')))
                price = r.get('price')
                if price is not None and price > 0:
                    result[code] = {
                        'code': code,
                        'name': r.get('name', ''),
                        'price': float(price),
                        'open': _safe_val(r.get('open')),
                        'pre_close': _safe_val(r.get('last_close')),
                        'high': _safe_val(r.get('high')),
                        'low': _safe_val(r.get('low')),
                        'amount': _safe_val(r.get('amount_wan')) * 10000.0,
                    }
    except Exception as e:
        logging.warning(f'腾讯财经行情获取失败: {e}')

    # 2. mootdx 兜底
    missing = [c for c in stock_codes if c not in result]
    if missing and mootdx:
        try:
            df_mt = mootdx.get_realtime(missing)
            if not df_mt.empty:
                for _, r in df_mt.iterrows():
                    code = normalize_code(str(r.get('code', '')))
                    price = r.get('price')
                    if price is not None and price > 0:
                        result[code] = {
                            'code': code,
                            'name': str(r.get('name', '')),
                            'price': float(price),
                            'open': _safe_val(r.get('open')),
                            'pre_close': _safe_val(r.get('last_close')),
                            'high': _safe_val(r.get('high')),
                            'low': _safe_val(r.get('low')),
                            'amount': _safe_val(r.get('amount')),
                        }
        except Exception as e:
            logging.warning(f'mootdx 兜底获取失败: {e}')

    return result


# ════════════════════════════════════════════════════════════════════════════
# 📊  MA120 计算及历史切片
# ════════════════════════════════════════════════════════════════════════════

def get_ma120_and_price(code: str, target_date: str, is_today: bool, realtime_p: Optional[float] = None, mootdx: Optional[MootdxClient] = None) -> Tuple[Optional[float], Optional[float]]:
    """
    计算特定日期的 MA120 和当天价格。
    如果 target_date 是今天且有实时价，将实时价融入到最近一根K线中计算。
    """
    df = pd.DataFrame()
    # 1. 尝试 mootdx K线
    if mootdx:
        df = mootdx.get_kline(code, count=MA_WINDOW + 80)
    # 2. 尝试百度 K线
    if df.empty:
        df = get_baidu_kline(code)

    if df.empty or len(df) < MA_WINDOW:
        return None, None

    # 时间序列格式对齐
    df['date'] = pd.to_datetime(df['date'])
    target_dt = pd.to_datetime(target_date)

    # 历史日期切片
    df_filtered = df[df['date'].dt.date <= target_dt.date()].copy()
    if len(df_filtered) < MA_WINDOW:
        return None, None

    close_series = df_filtered['close'].astype(float).copy()

    # 如果是今天且有实时最新价格，进行盘中价格追加
    if is_today and realtime_p is not None and realtime_p > 0:
        last_k_date = df_filtered['date'].iloc[-1].date()
        if last_k_date == target_dt.date():
            close_series.iloc[-1] = realtime_p
        else:
            new_row = pd.Series([realtime_p], index=[len(close_series)])
            close_series = pd.concat([close_series, new_row]).reset_index(drop=True)

    # 计算 MA120
    ma120 = close_series.rolling(MA_WINDOW).mean().iloc[-1]
    final_price = close_series.iloc[-1]

    return (float(ma120), float(final_price)) if pd.notna(ma120) else (None, None)


# ════════════════════════════════════════════════════════════════════════════
# 💾  路径定位与 JSON 保存发布
# ════════════════════════════════════════════════════════════════════════════

def find_website_dir() -> Path:
    cwd = Path(".")
    if (cwd / "index.html").exists() and (cwd / "data").exists():
        return cwd
    parent = Path("..")
    if (parent / "index.html").exists() and (parent / "data").exists():
        return parent
    abs_path = Path("d:/work_doc/python_project/my_website")
    if abs_path.exists():
        return abs_path
    return Path("../my_website")


def save_and_publish_whitehorse_data(signals: Dict, all_status: List, target_date: str, no_publish: bool) -> None:
    try:
        # 组装完整 JSON
        data_json = {
            "update_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") if target_date == datetime.datetime.now().strftime("%Y-%m-%d") else f"{target_date} 15:00:00",
            "signals": {
                "buy2": signals["buy2"],
                "buy": signals["buy"],
                "sell": signals["sell"],
                "near": signals["near"]
            },
            "all_status": all_status
        }

        website_dir = find_website_dir()
        if not website_dir.exists():
            logging.warning("未找到 my_website 项目目录，跳过写出")
            return

        data_dir = website_dir / "data"
        data_dir.mkdir(exist_ok=True)
        
        # 1. 写入今日最新数据
        json_file = data_dir / "whitehorse_data.json"
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(data_json, f, ensure_ascii=False, indent=2)
        logging.info("成功保存白马股最新数据至：%s", json_file)

        # 2. 写入历史归档
        history_dir = data_dir / "history"
        history_dir.mkdir(exist_ok=True)
        history_file = history_dir / f"whitehorse_data_{target_date}.json"
        with open(history_file, "w", encoding="utf-8") as f:
            json.dump(data_json, f, ensure_ascii=False, indent=2)
        logging.info("成功保存白马股历史归档至：%s", history_file)

        # 3. Git 上传发布
        if no_publish:
            logging.info("启用 --no-publish，跳过自动 Git 提交与推送")
            return

        import subprocess
        logging.info("开始执行 Git 自动上传流程...")
        subprocess.run(["git", "-C", str(website_dir), "add", "data/"], check=True)
        
        status_res = subprocess.run(["git", "-C", str(website_dir), "status", "--porcelain"], capture_output=True, text=True)
        if not status_res.stdout.strip():
            logging.info("数据无变化，跳过 Git 提交")
            return

        commit_msg = f"auto: update whitehorse data {target_date}"
        subprocess.run(["git", "-C", str(website_dir), "commit", "-m", commit_msg], check=True)
        subprocess.run(["git", "-C", str(website_dir), "push"], check=True)
        logging.info("Git 自动推送完成！线上数据已更新。")
        
    except Exception as e:
        logging.error("保存或发布白马股数据失败: %s", e)


# ════════════════════════════════════════════════════════════════════════════
# 📢  钉钉推送消息构建
# ════════════════════════════════════════════════════════════════════════════

def send_dingtalk(token: str, title: str, content: str):
    if not token:
        logging.warning("未配置钉钉 Token，跳过推送")
        return
    url = f"https://oapi.dingtalk.com/robot/send?access_token={token}"
    payload = {"msgtype": "markdown", "markdown": {"title": title, "text": content}}
    try:
        r = requests.post(url, headers={'Content-Type': 'application/json'}, json=payload, timeout=12)
        if r.status_code == 200:
            logging.info("钉钉消息推送成功")
        else:
            logging.error("钉钉消息推送失败 HTTP %d", r.status_code)
    except Exception as e:
        logging.error("钉钉消息推送异常: %s", e)


def build_markdown_message(signals: Dict, is_friday: bool, target_date: str) -> Optional[Tuple[str, str]]:
    has_signals = bool(signals['buy'] or signals['buy2'] or signals['sell'] or signals['near'])
    
    if has_signals:
        title = "白马股均值回归调仓信号"
    elif is_friday:
        title = "白马股均值回归周监控总览"
    else:
        return None

    content = f"## 🐎 {title}\n> ⏳ 巡检时间：`{target_date}`\n\n"

    def _format_stock_lines(stock_list: List, show_sell=False) -> str:
        lines = []
        for s in stock_list:
            tag = f"[{s['type']}]"
            if show_sell:
                line = (f"- **{s['name']}** ({s['code']}) {tag}  \n"
                        f"  现价 **{s['price']:.2f}** | MA120 {s['ma']:.2f} | **卖点 {s['sell']:.2f}** | 偏离率 {s['gap_pct']:+.2f}%\n")
            elif 'buy2' in s:
                line = (f"- **{s['name']}** ({s['code']}) {tag}  \n"
                        f"  现价 **{s['price']:.2f}** | MA120 {s['ma']:.2f} | 一批买点 {s['buy1']:.2f} | **二批买点 {s['buy2']:.2f}** | 偏离 {s['gap_pct']:+.2f}%\n")
            else:
                line = (f"- **{s['name']}** ({s['code']}) {tag}  \n"
                        f"  现价 **{s['price']:.2f}** | MA120 {s['ma']:.2f} | 买点 {s['buy1']:.2f} | 偏离 {s['gap_pct']:+.2f}%\n")
            lines.append(line)
        return "".join(lines)

    if signals['buy2']:
        content += "### 🚨🚨 第二批加仓信号（MA120 × 0.78）\n> 价格进入深度低估区，建议分批加仓\n\n"
        content += _format_stock_lines(signals['buy2']) + "\n"

    if signals['buy']:
        content += "### 🚨 第一批买入信号（MA120 × 0.88）\n> 已触及首批建仓位，建议建立底仓\n\n"
        content += _format_stock_lines(signals['buy']) + "\n"

    if signals['sell']:
        content += "### 💰 横盘震荡型卖出信号（MA120 × 1.12）\n> 已经触及目标阻力，建议止盈离场\n\n"
        content += _format_stock_lines(signals['sell'], show_sell=True) + "\n"

    if signals['near']:
        content += "### 📉 即将到位预警（距买点 < 3%）\n"
        content += _format_stock_lines(signals['near']) + "\n"

    # 周五总览
    if is_friday:
        content += "### 📋 45 只白马股策略实时监控总览\n"
        categories = [('横盘型', '横盘震荡型'), ('趋势型', '趋势成长型'), ('持有型', '长期持有型')]
        for cat_key, cat_name in categories:
            cat_stocks = [s for s in signals['all_status'] if s['category'] == cat_key]
            if not cat_stocks:
                continue
            content += f"#### 🔹 {cat_name} ({len(cat_stocks)}只)\n"
            for s in cat_stocks:
                status_text = f"**{s['status']}**" if s['status'] != '正常' else '正常'
                points_info = f"买点 {s['buy1']:.2f} | 卖点 {s['sell']:.2f}" if cat_key == '横盘型' else f"买点 {s['buy1']:.2f}"
                content += f"- {s['emoji']} **{s['name']}**({s['code']}): 现价 {s['price']:.2f} | {points_info} | 偏离 {s['gap_pct']:+.2f}% | 状态: {status_text}\n"
            content += "\n"

    content += ("---\n"
                "> **白马股均值回归策略说明**  \n"
                "> ◽ **横盘震荡型**：MA120×0.88建仓，MA120×0.78加仓，MA120×1.12止盈卖出  \n"
                "> ◽ **趋势成长型**：MA120×0.88建仓，MA120×0.78加仓，跌破 MA55 止损卖出  \n"
                "> ◽ **长期持有型**：触及买点建仓，收股息长持，不设卖点止盈")
    return title, content


# ════════════════════════════════════════════════════════════════════════════
# 🚀  主分析执行逻辑
# ════════════════════════════════════════════════════════════════════════════

def run_whitehorse_analysis(target_date: str, no_publish: bool, dingtalk_token: str) -> None:
    now_today = datetime.datetime.now().strftime("%Y-%m-%d")
    is_today = (target_date == now_today)
    is_friday = (pd.to_datetime(target_date).weekday() == 4)

    logging.info("开始白马股巡检 (目标日期: %s, 是否为今天: %s)...", target_date, is_today)

    # 1. 尝试初始化连接 mootdx 
    mootdx = None
    try:
        mootdx = MootdxClient()
        _ = mootdx.client
    except Exception as e:
        logging.warning("mootdx 不可用，将完全使用百度日 K 线和腾讯财经行情: %s", e)
        mootdx = None

    # 2. 获取实时行情 (仅当计算今天时使用)
    all_stocks = {**RANGE_STOCKS, **TREND_STOCKS, **HOLD_STOCKS}
    quotes = {}
    if is_today:
        logging.info("抓取白马股实时行情...")
        quotes = get_realtime_quotes(list(all_stocks.keys()), mootdx)
    
    # 3. 计算所有股票的 MA120 和对应价格
    logging.info("计算 %d 只白马股的 MA120 及当日收盘价...", len(all_stocks))
    ma_cache = {}
    price_cache = {}
    
    for code in all_stocks:
        realtime_p = quotes.get(code, {}).get('price') if is_today else None
        ma, price = get_ma120_and_price(code, target_date, is_today, realtime_p, mootdx)
        if ma is not None and price is not None:
            ma_cache[code] = ma
            price_cache[code] = price
        else:
            logging.warning("%s 行情/均线数据获取失败", code)

    if mootdx:
        mootdx.close()

    logging.info("白马股行情及均线计算完成，有效 %d/%d 只", len(ma_cache), len(all_stocks))

    # 4. 分析信号
    signals = {"buy": [], "buy2": [], "sell": [], "near": [], "all_status": []}
    
    for code, name in all_stocks.items():
        price = price_cache.get(code, 0.0)
        ma = ma_cache.get(code, 0.0)
        
        if price <= 0.0 or ma <= 0.0:
            signals["all_status"].append({
                "code": code,
                "name": name,
                "price": 0.0,
                "ma": 0.0,
                "buy1": 0.0,
                "buy2": 0.0,
                "sell": 0.0,
                "gap_pct": 0.0,
                "status": "数据失效",
                "emoji": "❌",
                "category": "横盘型" if code in RANGE_STOCKS else ("趋势型" if code in TREND_STOCKS else "持有型")
            })
            continue

        buy1 = round(ma * BUY_RATIO1, 2)
        buy2 = round(ma * BUY_RATIO2, 2)
        sell = round(ma * RANGE_SELL, 2)
        gap_pct = round((price - buy1) / price * 100, 2)

        is_range = code in RANGE_STOCKS
        is_trend = code in TREND_STOCKS
        is_hold = code in HOLD_STOCKS

        status_str = '正常'
        emoji = '⚪'

        stock_info = {
            'code': code,
            'name': name,
            'price': price,
            'ma': ma,
            'buy1': buy1,
            'buy2': buy2,
            'gap_pct': gap_pct,
            'type': '横盘型' if is_range else ('趋势型' if is_trend else '持有型')
        }

        if is_range and price >= sell:
            status_str = '卖出信号'
            emoji = '💰'
            signals['sell'].append({**stock_info, 'sell': sell})
        elif price <= buy2:
            status_str = '二批加仓'
            emoji = '🚨🚨'
            signals['buy2'].append(stock_info)
        elif price <= buy1:
            status_str = '首批买入'
            emoji = '🚨'
            signals['buy'].append(stock_info)
        elif 0 < gap_pct <= NEAR_PCT:
            status_str = '即将到位'
            emoji = '📉'
            signals['near'].append(stock_info)

        signals['all_status'].append({
            "code": code,
            "name": name,
            "price": price,
            "ma": ma,
            "buy1": buy1,
            "buy2": buy2,
            "sell": sell if is_range else None,
            "gap_pct": gap_pct,
            "status": status_str,
            "emoji": emoji,
            "category": '横盘型' if is_range else ('趋势型' if is_trend else '持有型')
        })

    # 5. 钉钉推送
    res = build_markdown_message(signals, is_friday, target_date)
    if res and is_today:
        title, content = res
        send_dingtalk(dingtalk_token, title, content)
    else:
        logging.info("今日无交易信号且非周五，或为历史日期，跳过钉钉推送。")

    # 6. 保存数据 JSON 并发布
    save_and_publish_whitehorse_data(signals, signals["all_status"], target_date, no_publish)


# ════════════════════════════════════════════════════════════════════════════
# 🏁  主入口
# ════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="白马股 MA120 均值回归策略监控系统")
    parser.add_argument("--once", action="store_true", help="运行一次，随后退出")
    parser.add_argument("--webhook", default=DEFAULT_DINGTALK_TOKEN, help="自定义钉钉 Webhook Token")
    parser.add_argument("--no-publish", action="store_true", help="跳过自动推送 GitHub 网站仓库流程")
    parser.add_argument("--date", default=None, help="查询并生成历史白马股数据的日期 (YYYY-MM-DD)")
    args = parser.parse_args()

    log_format = "%(asctime)s [%(levelname)s] %(message)s"
    logging.basicConfig(level=logging.INFO, format=log_format, handlers=[
        logging.StreamHandler(sys.stdout)
    ])

    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    target_date = args.date.strip() if args.date else datetime.datetime.now().strftime("%Y-%m-%d")
    run_whitehorse_analysis(target_date, args.no_publish, args.webhook)


if __name__ == '__main__':
    main()
