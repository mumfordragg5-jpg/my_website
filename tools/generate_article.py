"""
科技马前卒 - 公众号文章生成工具

使用方法:
  python generate_article.py

运行后按提示输入新闻标题和来源，自动生成公众号文章。
需要先设置 OPENAI_API_KEY 环境变量，或在下方 CONFIG 中直接填入。

依赖安装:
  pip install openai
"""

import os
import re
import datetime
from openai import OpenAI

# ==================== 配置区 ====================

CONFIG = {
    # OpenAI API Key（优先读取环境变量，也可以直接填在这里）
    "api_key": os.getenv("OPENAI_API_KEY", "在这里填入你的API Key"),

    # 模型选择（gpt-4o 效果最好，gpt-4o-mini 便宜够用）
    "model": "gpt-4o",

    # 如果用其他兼容 OpenAI 接口的服务（如 DeepSeek），改这里
    "base_url": "https://api.openai.com/v1",

    # 输出目录
    "output_dir": "output",

    # 每页显示的文章数
    "page_size": 6,
}

# ==================== 提示词模板 ====================

SYSTEM_PROMPT = """你是一位资深财经自媒体作者，笔名"科技马前卒"，专注于解读国际财经新闻，面向中国读者撰写微信公众号文章。

你的风格特点：
- 犀利、有深度、善用比喻，既专业又不枯燥
- 语气自信但不傲慢，像一个见多识广的朋友在跟你聊天
- 擅长把复杂的国际财经概念用通俗的语言解释清楚
- 每篇文章都有独立观点和判断，不做简单的新闻搬运"""

ARTICLE_PROMPT_TEMPLATE = """请根据以下新闻信息，写一篇微信公众号文章。

新闻标题：{headline}
信息来源：{source}
补充信息：{extra_info}

严格按照以下要求写作：

一、文章结构（按此顺序）：
1. 【标题】中文标题，15-30字，要有冲击力和悬念感，让人忍不住点进来
2. 【开头钩子】一句话点题，加粗，制造紧张感或颠覆认知
3. 【发生了什么】2-3段简明扼要说清核心事实，要有具体数据
4. 【为什么重要】补充背景知识，让不了解的读者也能看懂
5. 【深度分析】文章核心，有逻辑推理和独到见解，分2-3个小节，每节用"01 02 03"编号+小标题
6. 【对中国的影响】要具体接地气：影响股市？汇率？哪个行业？普通人的钱包？
7. 【结尾】一句精炼金句收束全文，有力量感，让人想转发

二、风格要求：
- 短句为主，一段不超过3-4行，适合手机阅读
- 重要观点用 **加粗** 标注
- 善用比喻和类比让复杂概念通俗化
- 每个小节开头用设问句引入，保持阅读节奏
- 不要用"让我们""首先""其次"等教科书过渡词
- 信息来源自然提及（如"据彭博社报道"），增加可信度

三、禁止事项：
- 不要直接翻译原文，用自己的话重新组织
- 不要堆砌数据，每个数据都要解释意味着什么
- 不要写空洞套话，每句话都要有信息量
- 不要用"小编""宝宝们"等低质自媒体用语
- 不要在正文中使用emoji表情符号

四、格式要求：
- 用 Markdown 格式输出
- 文章开头第一行是标题（用 # 号）
- 结尾用一条分割线后写：*关注「科技马前卒」，了解更多国际新闻。觉得有价值，点个「在看」，让更多人看到。*

五、字数：1800-2800字"""

# ==================== 来源映射 ====================

SOURCE_MAP = {
    "1": "Bloomberg（彭博社）",
    "2": "Wall Street Journal（华尔街日报）",
    "3": "New York Times（纽约时报）",
    "4": "The Economist（经济学人）",
    "5": "Reuters（路透社）",
    "6": "Financial Times（金融时报）",
}

# ==================== 核心函数 ====================


def generate_article(headline, source, extra_info="无"):
    """调用 AI 生成文章"""
    client = OpenAI(
        api_key=CONFIG["api_key"],
        base_url=CONFIG["base_url"],
    )

    user_prompt = ARTICLE_PROMPT_TEMPLATE.format(
        headline=headline,
        source=source,
        extra_info=extra_info if extra_info else "无",
    )

    print("\n⏳ 正在生成文章，请稍等...\n")

    response = client.chat.completions.create(
        model=CONFIG["model"],
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.7,
        max_tokens=4096,
    )

    return response.choices[0].message.content


def extract_title(content):
    """从 Markdown 内容中提取标题"""
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return "untitled"


def sanitize_filename(name):
    """生成安全的文件名"""
    name = re.sub(r'[\\/*?:"<>|]', '', name)
    name = name.replace(" ", "-")
    if len(name) > 60:
        name = name[:60]
    return name


def save_article(content, headline):
    """保存文章到文件"""
    os.makedirs(CONFIG["output_dir"], exist_ok=True)

    date_str = datetime.date.today().strftime("%Y%m%d")
    title = extract_title(content)
    safe_name = sanitize_filename(title)
    filename = f"{date_str}_{safe_name}.md"
    filepath = os.path.join(CONFIG["output_dir"], filename)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    return filepath


# ==================== 交互界面 ====================


def print_banner():
    print("=" * 56)
    print("   🏇 科技马前卒 - 公众号文章生成工具")
    print("=" * 56)
    print()


def get_source():
    print("信息来源（输入编号）：")
    for key, val in SOURCE_MAP.items():
        print(f"  {key}. {val}")
    print(f"  0. 其他（手动输入）")
    print()

    choice = input("选择 [1-6, 0]: ").strip()
    if choice in SOURCE_MAP:
        return SOURCE_MAP[choice]
    else:
        return input("请输入来源名称: ").strip() or "国际媒体"


def main():
    print_banner()

    headline = input("📰 粘贴英文新闻标题:\n> ").strip()
    if not headline:
        print("❌ 标题不能为空")
        return

    print()
    source = get_source()

    print()
    print("📝 补充信息（可选，直接回车跳过）：")
    print("   提示：粘贴文章前几段的关键数据，能提高准确度")
    extra_info = input("> ").strip()

    print()
    print(f"  标题：{headline}")
    print(f"  来源：{source}")
    if extra_info:
        print(f"  补充：{extra_info[:50]}...")
    print()

    try:
        content = generate_article(headline, source, extra_info)
    except Exception as e:
        print(f"❌ 生成失败: {e}")
        print()
        print("常见原因：")
        print("  1. API Key 未设置或无效")
        print("  2. 网络连接问题")
        print("  3. API 余额不足")
        return

    filepath = save_article(content, headline)

    print("✅ 文章生成完成！")
    print(f"📄 已保存到: {filepath}")
    print()
    print("-" * 56)
    print(content)
    print("-" * 56)
    print()
    print(f"📄 文件路径: {filepath}")
    print("📋 你可以直接复制上方内容到公众号编辑器")


if __name__ == "__main__":
    main()
