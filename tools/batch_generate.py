"""
科技马前卒 - 批量文章生成工具

使用方法:
  1. 编辑下方 HEADLINES 列表，填入今天要写的新闻标题
  2. 运行: python batch_generate.py
  3. 所有文章自动生成到 output/ 目录

依赖安装:
  pip install openai
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from generate_article import generate_article, save_article, CONFIG

# ==================== 在这里填入今天的选题 ====================

HEADLINES = [
    {
        "headline": "Chinese Markets Weather Iran War Turmoil Better Than Asian Peers",
        "source": "Bloomberg（彭博社）",
        "extra_info": "沪深300跌幅仅1.2%，日经225跌3.5%，KOSPI跌4.1%",
    },
    # 取消下方注释，添加更多选题：
    # {
    #     "headline": "在这里填英文标题",
    #     "source": "Wall Street Journal（华尔街日报）",
    #     "extra_info": "可选的补充信息",
    # },
]

# ==================== 执行 ====================


def main():
    if not HEADLINES:
        print("❌ 请先在 HEADLINES 列表中填入新闻标题")
        return

    print(f"🏇 科技马前卒 - 批量生成 {len(HEADLINES)} 篇文章")
    print("=" * 50)

    results = []

    for i, item in enumerate(HEADLINES, 1):
        headline = item["headline"]
        source = item.get("source", "国际媒体")
        extra_info = item.get("extra_info", "")

        print(f"\n[{i}/{len(HEADLINES)}] {headline[:50]}...")

        try:
            content = generate_article(headline, source, extra_info)
            filepath = save_article(content, headline)
            results.append({"headline": headline, "filepath": filepath, "ok": True})
            print(f"  ✅ 已保存: {filepath}")
        except Exception as e:
            results.append({"headline": headline, "error": str(e), "ok": False})
            print(f"  ❌ 失败: {e}")

    print("\n" + "=" * 50)
    print("📊 生成结果：")
    ok_count = sum(1 for r in results if r["ok"])
    print(f"  成功: {ok_count} / {len(results)}")
    for r in results:
        status = "✅" if r["ok"] else "❌"
        info = r.get("filepath", r.get("error", ""))
        print(f"  {status} {r['headline'][:40]}... -> {info}")


if __name__ == "__main__":
    main()
