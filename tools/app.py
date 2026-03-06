"""
科技马前卒 - Web 服务主程序

启动方式：
  python app.py

功能：
  1. Web 后台 - 网页提交话题，一键生成+发布
  2. 钉钉机器人 - 在钉钉群 @机器人 发送话题自动生成
  3. API 接口 - 供其他系统调用

接口：
  GET  /                    管理后台页面
  POST /api/generate        生成文章
  POST /api/publish         发布文章
  POST /api/dingtalk        钉钉机器人 Webhook
"""

import os
import sys
import datetime
import markdown

from flask import Flask, request, jsonify, render_template

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import FLASK_HOST, FLASK_PORT, FLASK_SECRET_KEY
from article_generator import generate_article
from website_publisher import publish_to_website
from dingtalk_handler import verify_dingtalk_signature, parse_dingtalk_message, build_dingtalk_response

app = Flask(__name__)
app.secret_key = FLASK_SECRET_KEY


# ==================== 页面路由 ====================


@app.route("/")
def index():
    return render_template("index.html")


# ==================== API: 生成文章 ====================


@app.route("/api/generate", methods=["POST"])
def api_generate():
    data = request.get_json()
    headline = data.get("headline", "").strip()
    source = data.get("source", "国际媒体")
    extra_info = data.get("extra_info", "")
    tags = data.get("tags", ["热点"])

    if not headline:
        return jsonify({"success": False, "error": "标题不能为空"})

    try:
        article = generate_article(headline, source, extra_info)

        html_preview = markdown.markdown(article["content"], extensions=["extra"])

        return jsonify({
            "success": True,
            "title": article["title"],
            "markdown": article["content"],
            "html_preview": html_preview,
            "source": source,
            "tags": tags,
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


# ==================== API: 发布文章 ====================


@app.route("/api/publish", methods=["POST"])
def api_publish():
    data = request.get_json()
    title = data.get("title", "")
    content = data.get("content", "")
    tags = data.get("tags", ["热点"])
    source = data.get("source", "国际媒体")
    publish_to = data.get("publish_to", "both")

    if not content:
        return jsonify({"success": False, "error": "文章内容为空"})

    result = {"success": True, "website": None, "wechat": None}

    article_data = {
        "title": title,
        "content": content,
        "headline": title,
        "source": source,
    }

    if publish_to in ("both", "website"):
        try:
            url = publish_to_website(article_data, tags)
            result["website"] = url if url else "未配置仓库路径"
        except Exception as e:
            result["website"] = f"失败: {e}"

    if publish_to in ("both", "wechat"):
        try:
            wechat_result = publish_to_wechat(title, content)
            result["wechat"] = wechat_result
        except Exception as e:
            result["wechat"] = f"失败: {e}"

    return jsonify(result)


def publish_to_wechat(title: str, content: str) -> str:
    """
    微信公众号发布接口。

    ===== 在这里对接你已有的微信发布代码 =====

    你之前写的自动发布代码放在这里调用即可，例如：
      from your_wechat_module import auto_publish
      auto_publish(title, content)
    """
    return "微信发布接口待对接（请在 app.py 的 publish_to_wechat 函数中接入你的代码）"


# ==================== API: 钉钉机器人 ====================


@app.route("/api/dingtalk", methods=["POST"])
def api_dingtalk():
    timestamp = request.headers.get("timestamp", "")
    sign = request.headers.get("sign", "")

    if not verify_dingtalk_signature(timestamp, sign):
        return jsonify({"msgtype": "text", "text": {"content": "签名验证失败"}})

    data = request.get_json()
    msg = parse_dingtalk_message(data)

    if not msg["headline"]:
        return jsonify({
            "msgtype": "text",
            "text": {"content": "请发送新闻标题，例如：\nBloomberg: Some Headline Here\n或直接发送中英文标题"},
        })

    try:
        article = generate_article(msg["headline"], msg["source"], msg["extra_info"])

        url = publish_to_website(article, ["热点"])

        return jsonify(build_dingtalk_response(article["title"], url))

    except Exception as e:
        return jsonify(build_dingtalk_response("", error=str(e)))


# ==================== 启动 ====================

if __name__ == "__main__":
    print("=" * 50)
    print("  🏇 科技马前卒 - 文章管理后台")
    print("=" * 50)
    print(f"  管理后台: http://localhost:{FLASK_PORT}")
    print(f"  钉钉接口: http://your-server:{FLASK_PORT}/api/dingtalk")
    print("=" * 50)
    print()

    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=True)
