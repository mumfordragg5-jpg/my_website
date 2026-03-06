"""
科技马前卒 - 钉钉机器人处理模块

支持两种方式接入钉钉：
1. 群机器人 Outgoing Webhook：在群里 @机器人 发消息触发
2. 直接调用：其他系统通过 HTTP 调用
"""

import time
import hmac
import hashlib
import base64
from config import DINGTALK_SECRET


def verify_dingtalk_signature(timestamp: str, sign: str) -> bool:
    """验证钉钉请求签名"""
    if not DINGTALK_SECRET:
        return True

    string_to_sign = f"{timestamp}\n{DINGTALK_SECRET}"
    hmac_code = hmac.new(
        DINGTALK_SECRET.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    expected_sign = base64.b64encode(hmac_code).decode("utf-8")

    return sign == expected_sign


def parse_dingtalk_message(data: dict) -> dict:
    """
    解析钉钉消息，提取话题信息。

    支持的消息格式：
      @机器人 写文章 标题内容
      @机器人 Bloomberg: Some Headline Here
      @机器人 WSJ: Some Headline Here

    Returns:
        {"headline": "...", "source": "...", "extra_info": "...", "sender": "..."}
    """
    text = data.get("text", {}).get("content", "").strip()
    sender = data.get("senderNick", "unknown")

    source_prefixes = {
        "bloomberg:": "Bloomberg（彭博社）",
        "wsj:": "Wall Street Journal（华尔街日报）",
        "nyt:": "New York Times（纽约时报）",
        "economist:": "The Economist（经济学人）",
        "reuters:": "Reuters（路透社）",
        "ft:": "Financial Times（金融时报）",
    }

    source = "国际媒体"
    headline = text

    for prefix_key in ["写文章", "写一篇", "生成"]:
        if headline.startswith(prefix_key):
            headline = headline[len(prefix_key):].strip()
            break

    for prefix, src_name in source_prefixes.items():
        if headline.lower().startswith(prefix):
            source = src_name
            headline = headline[len(prefix):].strip()
            break

    parts = headline.split("|", 1)
    extra_info = ""
    if len(parts) == 2:
        headline = parts[0].strip()
        extra_info = parts[1].strip()

    return {
        "headline": headline,
        "source": source,
        "extra_info": extra_info,
        "sender": sender,
    }


def build_dingtalk_response(title: str, url: str = "", error: str = "") -> dict:
    """构建钉钉回复消息"""
    if error:
        return {
            "msgtype": "text",
            "text": {"content": f"❌ 生成失败：{error}"},
        }

    content = f"✅ 文章已生成\n\n📄 {title}"
    if url:
        content += f"\n🔗 {url}"
    content += "\n\n文章已自动发布到网站"

    return {
        "msgtype": "text",
        "text": {"content": content},
    }
