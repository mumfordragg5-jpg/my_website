"""
科技马前卒 - 微信公众号发布模块

包含：
1. Markdown -> 微信公众号 HTML 转换
2. 获取 access_token
3. 发布到草稿箱

原始代码完整保留，仅封装为模块。
"""

import json
import re
from typing import Any, Dict

import requests

from config import WX_APPID, WX_APPSECRET, WX_THUMB_MEDIA_ID, WX_AUTHOR


# ==================== Markdown -> 微信 HTML ====================


def markdown_to_wx_html(md_text: str) -> str:
    """将 Markdown 文本转为适配微信公众号的 HTML"""
    lines = md_text.split("\n")
    html_parts = []
    in_list = False

    for line in lines:
        stripped = line.strip()

        if not stripped:
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            html_parts.append("<br/>")
            continue

        if stripped.startswith("---") or stripped.startswith("***") or stripped.startswith("___"):
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            html_parts.append(
                "<hr style='border:none; border-top:1px solid #ddd; margin:20px 0;'/>"
            )
            continue

        if stripped.startswith("- ") or stripped.startswith("• "):
            if not in_list:
                html_parts.append("<ul style='font-size:15px; line-height:1.8; padding-left:20px;'>")
                in_list = True
            item_text = _inline_format(stripped[2:])
            html_parts.append(f"<li>{item_text}</li>")
            continue

        if in_list:
            html_parts.append("</ul>")
            in_list = False

        heading_match = re.match(r"^(#{1,3})\s+(.+)$", stripped)
        if heading_match:
            level = len(heading_match.group(1))
            text = _inline_format(heading_match.group(2))
            sizes = {1: "20px", 2: "17px", 3: "16px"}
            font_size = sizes.get(level, "16px")
            html_parts.append(
                f"<h{level} style='font-size:{font_size}; font-weight:bold; "
                f"color:#333; margin:18px 0 10px 0;'>{text}</h{level}>"
            )
            continue

        numbered_heading = re.match(r"^(0[1-9]|[1-9]\d?)\s+(.+)$", stripped)
        if numbered_heading:
            num = numbered_heading.group(1)
            text = _inline_format(numbered_heading.group(2))
            html_parts.append(
                f"<h3 style='font-size:16px; font-weight:bold; color:#333; "
                f"margin:18px 0 10px 0;'>"
                f"<span style='color:#c0392b; font-weight:bold;'>{num}</span> {text}</h3>"
            )
            continue

        text = _inline_format(stripped)
        html_parts.append(
            f"<p style='font-size:15px; line-height:1.8; color:#333; "
            f"margin:8px 0; text-align:justify;'>{text}</p>"
        )

    if in_list:
        html_parts.append("</ul>")

    return "\n".join(html_parts)


def _inline_format(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"<b style='color:#c0392b;'>\1</b>", text)
    text = re.sub(r"\*(.+?)\*", r"<em style='color:#555;'>\1</em>", text)
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    return text


# ==================== 微信 API ====================


def get_wx_access_token() -> str:
    url = "https://api.weixin.qq.com/cgi-bin/token"
    params = {
        "grant_type": "client_credential",
        "appid": WX_APPID,
        "secret": WX_APPSECRET,
    }
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()
    if "access_token" not in data:
        raise RuntimeError(f"获取 access_token 失败: {data}")
    return data["access_token"]


def publish_to_wechat_draft(title: str, md_content: str) -> Dict[str, Any]:
    """
    发布文章到微信公众号草稿箱

    Args:
        title: 文章标题
        md_content: Markdown 格式正文

    Returns:
        微信 API 返回结果，包含 media_id
    """
    html_content = markdown_to_wx_html(md_content)
    token = get_wx_access_token()

    url = f"https://api.weixin.qq.com/cgi-bin/draft/add?access_token={token}"
    payload = {
        "articles": [
            {
                "title": title,
                "content": html_content,
                "content_source_url": "",
                "thumb_media_id": WX_THUMB_MEDIA_ID,
                "author": WX_AUTHOR,
                "digest": title[:60],
                "show_cover_pic": 0,
                "need_open_comment": 1,
                "only_fans_can_comment": 0,
            }
        ]
    }
    headers = {"Content-Type": "application/json; charset=utf-8"}
    r = requests.post(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        timeout=30,
    )
    r.raise_for_status()
    result = r.json()

    media_id = result.get("media_id")
    if media_id:
        print(f"[微信公众号] 发布成功! media_id = {media_id}")
    else:
        print(f"[微信公众号] 发布异常: {result}")

    return result
