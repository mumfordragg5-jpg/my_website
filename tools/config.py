"""
科技马前卒 - 全局配置

所有密钥和配置集中在这里管理。
优先读取环境变量，方便部署时不改代码。
"""

import os

# DeepSeek API
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "在这里填入你的DeepSeek API Key")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

# 钉钉机器人（Outgoing Webhook）
DINGTALK_SECRET = os.getenv("DINGTALK_SECRET", "")  # 钉钉机器人的签名密钥

# GitHub 网站仓库（用于自动发布文章到网站）
GITHUB_REPO_PATH = os.getenv("GITHUB_REPO_PATH", "")  # 本地仓库路径，如 /Users/you/my_website
GITHUB_AUTO_PUSH = os.getenv("GITHUB_AUTO_PUSH", "true").lower() == "true"

# 微信公众号（对接你已有的发布代码）
WECHAT_APPID = os.getenv("WECHAT_APPID", "")
WECHAT_SECRET = os.getenv("WECHAT_SECRET", "")

# Flask
FLASK_HOST = os.getenv("FLASK_HOST", "0.0.0.0")
FLASK_PORT = int(os.getenv("FLASK_PORT", "5000"))
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "keji-maqianzu-2026")
