"""
科技马前卒 - 文章生成核心模块

调用 DeepSeek API 生成公众号文章，返回 Markdown 格式。
"""

import re
from openai import OpenAI
from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

SYSTEM_PROMPT = """你是一位资深财经自媒体作者，笔名"科技马前卒"，专注于解读国际财经新闻，面向中国读者撰写微信公众号文章。

你的风格特点：
- 犀利、有深度、善用比喻，既专业又不枯燥
- 语气自信但不傲慢，像一个见多识广的朋友在跟你聊天
- 擅长把复杂的国际财经概念用通俗的语言解释清楚
- 每篇文章都有独立观点和判断，不做简单的新闻搬运"""

ARTICLE_PROMPT = """请根据以下新闻信息，写一篇微信公众号文章。

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


def generate_article(headline: str, source: str = "国际媒体", extra_info: str = "") -> dict:
    """
    生成文章，返回 dict:
    {
        "title": "中文标题",
        "content": "完整 Markdown 内容",
        "headline": "原始英文标题",
        "source": "来源",
    }
    """
    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

    prompt = ARTICLE_PROMPT.format(
        headline=headline,
        source=source,
        extra_info=extra_info or "无",
    )

    response = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.7,
        max_tokens=4096,
    )

    content = response.choices[0].message.content
    title = _extract_title(content)

    return {
        "title": title,
        "content": content,
        "headline": headline,
        "source": source,
    }


def _extract_title(md_content: str) -> str:
    for line in md_content.split("\n"):
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return "未命名文章"


def sanitize_slug(text: str) -> str:
    """生成 URL 友好的 slug"""
    text = re.sub(r'[^\w\u4e00-\u9fff\s-]', '', text)
    text = re.sub(r'[\s]+', '-', text.strip())
    return text[:50] if len(text) > 50 else text
