"""
科技马前卒 - 命令行入口

用法：
  # 话题模式（自动抓新闻 + 生成）
  python generate_article.py "美联储加息"
  python generate_article.py "特朗普关税" --publish

  # 标题模式
  python generate_article.py --headline "Fed Raises Interest Rates" --source bloomberg

  # 保存到文件
  python generate_article.py "日元贬值" --save output.md
"""

import os
import sys
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import DEEPSEEK_API_KEY
from article_generator import generate_by_topic, generate_by_headline
from wechat_publisher import publish_to_wechat_draft


def main():
    parser = argparse.ArgumentParser(description="科技马前卒 - 公众号文章生成器")
    parser.add_argument("topic", nargs="?", type=str, help="话题关键词（话题模式）")
    parser.add_argument("--headline", type=str, help="英文标题（标题模式）")
    parser.add_argument("--source", type=str, default="国际媒体", help="来源: bloomberg/wsj/nyt/economist")
    parser.add_argument("--extra", type=str, default="", help="补充信息")
    parser.add_argument("--publish", action="store_true", help="自动发布到微信公众号草稿箱")
    parser.add_argument("--save", type=str, default="", help="保存到文件")

    args = parser.parse_args()

    if DEEPSEEK_API_KEY == "your-deepseek-api-key":
        print("错误：请先在 config.py 中配置 DEEPSEEK_API_KEY")
        sys.exit(1)

    source_map = {
        "bloomberg": "Bloomberg（彭博社）",
        "wsj": "Wall Street Journal（华尔街日报）",
        "nyt": "New York Times（纽约时报）",
        "economist": "The Economist（经济学人）",
        "reuters": "Reuters（路透社）",
        "ft": "Financial Times（金融时报）",
    }

    print("=" * 56)
    print("   🏇 科技马前卒 - 文章生成器")
    print(f"   时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 56 + "\n")

    if args.headline:
        source = source_map.get(args.source.lower(), args.source)
        print(f"[模式] 标题模式")
        print(f"[标题] {args.headline}")
        print(f"[来源] {source}\n")
        article = generate_by_headline(args.headline, source, args.extra)
    elif args.topic:
        print(f"[模式] 话题模式（自动抓取新闻）")
        print(f"[话题] {args.topic}\n")
        article = generate_by_topic(args.topic)
    else:
        parser.print_help()
        sys.exit(1)

    print(f"[结果] 标题: {article['title']}")
    print(f"[结果] 字数: {len(article['content'])}\n")

    if args.save:
        with open(args.save, "w", encoding="utf-8") as f:
            f.write(article["content_full"])
        print(f"[保存] {args.save}")

    if args.publish:
        print("[微信] 正在发布到草稿箱...")
        try:
            publish_to_wechat_draft(article["title"], article["content"])
        except Exception as e:
            print(f"[微信] 发布失败: {e}")

    print("\n" + "=" * 56)
    print(article["content_full"])
    print("=" * 56)
    print("\n完成！")


if __name__ == "__main__":
    main()
