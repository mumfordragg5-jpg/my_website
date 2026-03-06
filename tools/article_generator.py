"""
科技马前卒 - 文章生成核心模块

两种生成模式：
1. 话题模式：输入话题 -> 自动抓取新闻 -> 生成文章（你原来的流程）
2. 标题模式：直接输入英文标题 -> 生成文章（快速模式）
"""

import time
from typing import Dict

from openai import OpenAI

from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
from news_fetcher import aggregate_news, format_news_for_prompt

# ==================== 提示词 ====================

SYSTEM_PROMPT = """你是一位资深财经自媒体作者，笔名"科技马前卒"，专注于解读国际财经新闻，面向中国读者撰写微信公众号文章。你的风格犀利、有深度、善用比喻，既专业又不枯燥。"""

# 模式一：话题 + 新闻素材
TOPIC_PROMPT = """请根据以下新闻素材，围绕「{topic}」这个话题，帮我写一篇公众号文章。

参考新闻素材：
{news_material}

写作要求：

一、文章结构（严格按照以下顺序）：
1. 标题：中文，要有冲击力和悬念感，15-30字，可以用问号或感叹号，要让人忍不住点进来
2. 开头钩子：一句话点题，加粗，制造紧张感或颠覆认知
3. 发生了什么：用2-3段简明扼要说清核心事实，要有具体数据
4. 为什么重要：补充背景知识，让不了解的读者也能看懂
5. 深度分析：这是文章的核心，要有你自己的逻辑推理和独到见解，分2-3个小节展开，每节用"01 02 03"编号+小标题
6. 对中国的影响：读者最关心这个，要具体、接地气（影响股市？汇率？某个行业？普通人的钱包？）
7. 结尾：用一句精炼的金句收束全文，要有力量感，让人想转发

二、风格要求：
- 短句为主，一段不超过3-4行，适合手机阅读
- 重要观点用**加粗**标注
- 善用比喻和类比让复杂概念通俗化
- 语气自信但不傲慢，像一个见多识广的朋友在跟你聊天
- 每个小节开头用设问句引入，保持阅读节奏
- 不要用"让我们""首先""其次"这类教科书式的过渡词
- 信息来源要自然提及（如"据彭博社报道"），增加可信度

三、禁止事项：
- 不要直接翻译原文，要用自己的话重新组织
- 不要堆砌数据，每个数据都要解释它意味着什么
- 不要写空洞的套话，每句话都要有信息量
- 不要用"小编""宝宝们"等低质自媒体用语
- 不要在文中使用emoji表情符号

四、结尾固定格式：
用一条分割线后写上：
*关注「科技马前卒」，了解更多国际新闻。觉得有价值，点个「在看」，让更多人看到。*

文章字数：1800-2800字。
请直接输出文章内容，不要加任何额外说明。标题单独一行放在最前面。"""

# 模式二：直接给标题
HEADLINE_PROMPT = """请根据以下新闻信息，写一篇微信公众号文章。

新闻标题：{headline}
信息来源：{source}
补充信息：{extra_info}

写作要求同上（结构、风格、禁止事项完全一致）。

一、文章结构（严格按照以下顺序）：
1. 标题：中文，15-30字，有冲击力和悬念感
2. 开头钩子：一句话点题，加粗
3. 发生了什么：2-3段，有具体数据
4. 为什么重要：补充背景知识
5. 深度分析：2-3个小节，用"01 02 03"编号+小标题
6. 对中国的影响：具体、接地气
7. 结尾：精炼金句

二、风格：短句为主，重要观点**加粗**，善用比喻，语气自信但不傲慢，自然提及信息来源。
三、禁止：直接翻译、堆砌数据、空洞套话、低质用语、emoji。
四、结尾分割线后写：*关注「科技马前卒」，了解更多国际新闻。觉得有价值，点个「在看」，让更多人看到。*

字数：1800-2800字。标题单独一行放在最前面。"""


# ==================== 生成函数 ====================


def generate_by_topic(topic: str) -> Dict:
    """
    话题模式：自动抓新闻 + 生成文章（你原来的流程）
    """
    news_list = aggregate_news(topic)

    if not news_list:
        news_material = f"话题：{topic}\n（未找到具体新闻报道，请基于你的知识储备撰写）"
    else:
        news_material = format_news_for_prompt(news_list)
        print("[新闻素材预览]")
        for item in news_list[:5]:
            from news_fetcher import identify_source
            src = identify_source(item.get("source", ""))
            print(f"  - [{src}] {item['title'][:80]}")
        print()

    prompt = TOPIC_PROMPT.format(topic=topic, news_material=news_material)
    result = _call_deepseek(prompt)
    result["news_sources"] = news_list
    result["mode"] = "topic"
    return result


def generate_by_headline(headline: str, source: str = "国际媒体", extra_info: str = "") -> Dict:
    """
    标题模式：直接给标题，快速生成
    """
    prompt = HEADLINE_PROMPT.format(
        headline=headline,
        source=source,
        extra_info=extra_info or "无",
    )
    result = _call_deepseek(prompt)
    result["headline"] = headline
    result["source"] = source
    result["mode"] = "headline"
    return result


def _call_deepseek(user_prompt: str) -> Dict:
    """统一的 DeepSeek API 调用"""
    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

    print("[DeepSeek] 正在生成文章，请稍候...")
    start = time.time()

    response = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.7,
        max_tokens=4096,
    )

    elapsed = time.time() - start
    raw = response.choices[0].message.content.strip()
    print(f"[DeepSeek] 生成完成，耗时 {elapsed:.1f}s，字数 {len(raw)}\n")

    title, content = _split_title_content(raw)

    return {
        "title": title,
        "content": content,
        "content_full": raw,
    }


def _split_title_content(raw_text: str) -> tuple:
    """分离标题和正文"""
    lines = raw_text.split("\n")
    title = ""
    content_lines = []
    for line in lines:
        stripped = line.strip()
        if not title and stripped:
            title = stripped.lstrip("#").strip()
            continue
        content_lines.append(line)
    return title, "\n".join(content_lines).strip()
