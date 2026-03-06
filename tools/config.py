"""
科技马前卒 - 全局配置
"""

import os

# DeepSeek API
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "your-deepseek-api-key")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

# 微信公众号
WX_APPID = os.getenv("WX_APPID", "111")
WX_APPSECRET = os.getenv("WX_APPSECRET", "222")
WX_THUMB_MEDIA_ID = os.getenv("WX_THUMB_MEDIA_ID", "mvY2aVVddZ1IF8KCyZvchZA9K4dOCC3uELki_OfhWofmEYlgvM0Ywky831xZ3W2H")
WX_AUTHOR = os.getenv("WX_AUTHOR", "科技马前卒")

# NewsAPI（可选，免费版每天100次）
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "")

# 钉钉机器人（Outgoing Webhook 的签名密钥）
DINGTALK_SECRET = os.getenv("DINGTALK_SECRET", "")

# GitHub 网站仓库（自动发布文章到 GitHub Pages）
GITHUB_REPO_PATH = os.getenv("GITHUB_REPO_PATH", "")  # 填本地仓库路径，如 /home/user/my_website
GITHUB_AUTO_PUSH = os.getenv("GITHUB_AUTO_PUSH", "true").lower() == "true"

# Flask
FLASK_HOST = os.getenv("FLASK_HOST", "0.0.0.0")
FLASK_PORT = int(os.getenv("FLASK_PORT", "5000"))
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "keji-maqianzu-2026")

# 媒体源映射
MEDIA_SOURCES = {
    "bloomberg": "彭博社",
    "wall street journal": "华尔街日报",
    "wsj": "华尔街日报",
    "new york times": "纽约时报",
    "nytimes": "纽约时报",
    "economist": "经济学人",
    "reuters": "路透社",
    "financial times": "金融时报",
    "ft": "金融时报",
    "cnbc": "CNBC",
    "bbc": "BBC",
}
