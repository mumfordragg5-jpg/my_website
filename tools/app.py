"""
科技马前卒 - Web 服务主程序

启动: python app.py

功能：
  1. Web 后台 - 网页提交话题/标题，一键生成+发布
  2. 钉钉机器人 - 群里 @机器人 发话题自动生成
  3. API 接口 - 供其他系统调用

接口一览：
  GET  /                    管理后台页面
  POST /api/generate        生成文章（标题模式 or 话题模式）
  POST /api/publish         发布文章到 网站/微信/两者
  POST /api/dingtalk        钉钉机器人 Webhook
"""

import os
import sys
import traceback

import markdown as md_lib
from flask import Flask, request, jsonify, render_template

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import FLASK_HOST, FLASK_PORT, FLASK_SECRET_KEY
from article_generator import generate_by_topic, generate_by_headline
from wechat_publisher import publish_to_wechat_draft
from website_publisher import publish_to_website
from dingtalk_handler import verify_dingtalk_signature, parse_dingtalk_message, build_dingtalk_response

app = Flask(__name__)
app.secret_key = FLASK_SECRET_KEY


@app.route("/")
def index():
    return render_template("index.html")


# ==================== 生成文章 ====================

@app.route("/api/generate", methods=["POST"])
def api_generate():
    """
    生成文章 API

    请求体:
    {
        "mode": "headline" | "topic",     # headline=直接给标题, topic=话题模式(抓新闻)
        "headline": "英文标题",            # mode=headline 时必填
        "topic": "话题关键词",             # mode=topic 时必填
        "source": "Bloomberg（彭博社）",   # 可选
        "extra_info": "补充信息",          # 可选
        "tags": ["市场", "中国"],          # 可选
    }
    """
    data = request.get_json()
    mode = data.get("mode", "headline")
    tags = data.get("tags", ["热点"])

    try:
        if mode == "topic":
            topic = data.get("topic", "").strip()
            if not topic:
                return jsonify({"success": False, "error": "话题不能为空"})
            article = generate_by_topic(topic)
        else:
            headline = data.get("headline", "").strip()
            if not headline:
                return jsonify({"success": False, "error": "标题不能为空"})
            source = data.get("source", "国际媒体")
            extra_info = data.get("extra_info", "")
            article = generate_by_headline(headline, source, extra_info)

        html_preview = md_lib.markdown(article["content_full"], extensions=["extra"])

        return jsonify({
            "success": True,
            "title": article["title"],
            "markdown": article["content_full"],
            "content": article["content"],
            "html_preview": html_preview,
            "source": data.get("source", ""),
            "tags": tags,
            "mode": article.get("mode"),
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)})


# ==================== 发布文章 ====================

@app.route("/api/publish", methods=["POST"])
def api_publish():
    """
    发布文章 API

    请求体:
    {
        "title": "文章标题",
        "content": "Markdown正文",
        "tags": ["市场"],
        "source": "Bloomberg",
        "publish_to": "both" | "website" | "wechat" | "none"
    }
    """
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
        "content_full": f"# {title}\n\n{content}",
        "headline": title,
        "source": source,
    }

    # 发布到网站
    if publish_to in ("both", "website"):
        try:
            url = publish_to_website(article_data, tags)
            result["website"] = url if url else "未配置 GITHUB_REPO_PATH"
        except Exception as e:
            result["website"] = f"失败: {e}"

    # 发布到微信公众号草稿箱
    if publish_to in ("both", "wechat"):
        try:
            wx_result = publish_to_wechat_draft(title, content)
            media_id = wx_result.get("media_id", "")
            result["wechat"] = f"成功, media_id={media_id}" if media_id else f"异常: {wx_result}"
        except Exception as e:
            result["wechat"] = f"失败: {e}"

    return jsonify(result)


# ==================== 钉钉机器人 ====================

@app.route("/api/dingtalk", methods=["POST"])
def api_dingtalk():
    """
    钉钉 Outgoing Webhook

    在群里 @机器人 发送消息格式：
      Bloomberg: Some Headline Here
      话题 美联储加息
      WSJ: Oil Prices Surge
    """
    timestamp = request.headers.get("timestamp", "")
    sign = request.headers.get("sign", "")

    if not verify_dingtalk_signature(timestamp, sign):
        return jsonify({"msgtype": "text", "text": {"content": "签名验证失败"}})

    data = request.get_json()
    msg = parse_dingtalk_message(data)

    if not msg["headline"]:
        return jsonify({
            "msgtype": "text",
            "text": {
                "content": (
                    "请发送新闻标题或话题，例如：\n"
                    "Bloomberg: Some Headline\n"
                    "话题 美联储加息\n"
                    "WSJ: Oil Prices Surge | 油价涨到120美元"
                )
            },
        })

    try:
        # 判断模式：以"话题"开头走话题模式，否则走标题模式
        if msg.get("is_topic"):
            article = generate_by_topic(msg["headline"])
        else:
            article = generate_by_headline(msg["headline"], msg["source"], msg["extra_info"])

        # 自动发布到网站和微信
        website_url = ""
        try:
            website_url = publish_to_website(article, ["热点"])
        except Exception:
            pass

        try:
            publish_to_wechat_draft(article["title"], article["content"])
        except Exception:
            pass

        return jsonify(build_dingtalk_response(article["title"], website_url))

    except Exception as e:
        return jsonify(build_dingtalk_response("", error=str(e)))


# ==================== 启动 ====================

if __name__ == "__main__":
    print("=" * 56)
    print("   🏇 科技马前卒 - 文章管理后台")
    print("=" * 56)
    print(f"   管理后台:  http://localhost:{FLASK_PORT}")
    print(f"   钉钉接口:  http://your-server:{FLASK_PORT}/api/dingtalk")
    print(f"   生成API:   POST /api/generate")
    print(f"   发布API:   POST /api/publish")
    print("=" * 56)
    print()

    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=True)
