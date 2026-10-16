"""
公众号导出 —— 生成可"复制粘贴进编辑器"的内联样式 HTML

要点：
  微信公众号编辑器会剥离 <style> 与 class，所以必须**全部内联**。
  同时 公众号 对外链、脚本有限制，这里只产出安全的 section/span/p。

排版面向 50-70 岁读者：字号 16px、行高 1.8、段间距充足。
"""

import html as ht
import re

FONT_STACK = ('-apple-system,BlinkMacSystemFont,"Helvetica Neue","PingFang SC",'
              '"Hiragino Sans GB","Microsoft YaHei",sans-serif')

# 主题色（可按需改）
PRIMARY = "#c0504d"      # 小标题左侧色条 / 强调色（暖红，适合中老年审美）
TEXT = "#3f3f3f"
SUB = "#888888"
BG_SOFT = "#f7f4f1"


def _esc(s):
    return ht.escape(s or "", quote=False)


def _inline_md(s):
    """处理 **加粗** 与 `code`"""
    s = _esc(s)
    s = re.sub(r"\*\*(.+?)\*\*",
               r'<strong style="color:%s;font-weight:600;">\1</strong>' % PRIMARY, s)
    s = re.sub(r"`(.+?)`",
               r'<code style="background:%s;color:%s;padding:1px 5px;border-radius:3px;'
               r'font-size:15px;">\1</code>' % (BG_SOFT, PRIMARY), s)
    return s


def body_to_wechat_html(body):
    """把草稿正文（Markdown 子集）转成 公众号 可粘贴 HTML"""
    lines = (body or "").splitlines()
    out = []
    buf = []

    def flush_para():
        if not buf:
            return
        text = " ".join(x.strip() for x in buf if x.strip())
        if text:
            out.append(
                '<p style="margin:0 0 18px;font-size:16px;line-height:1.8;'
                'color:%s;letter-spacing:0.5px;text-align:justify;">%s</p>'
                % (TEXT, _inline_md(text))
            )
        buf.clear()

    for raw in lines:
        line = raw.rstrip()
        s = line.strip()

        if not s:
            flush_para()
            continue

        # 一级小标题  ## 
        m = re.match(r"^#{2,6}\s*(.+)$", s)
        if m:
            flush_para()
            out.append(
                '<section style="margin:28px 0 14px;">'
                '<span style="display:inline-block;border-left:4px solid %s;'
                'padding-left:10px;font-size:17px;font-weight:600;color:#2b2b2b;'
                'line-height:1.4;letter-spacing:0.5px;">%s</span></section>'
                % (PRIMARY, _inline_md(m.group(1)))
            )
            continue

        # 引用 >
        if s.startswith(">"):
            flush_para()
            out.append(
                '<section style="margin:0 0 18px;padding:12px 14px;background:%s;'
                'border-radius:6px;font-size:15px;line-height:1.75;color:#666;">%s</section>'
                % (BG_SOFT, _inline_md(s.lstrip("> ").strip()))
            )
            continue

        # 分隔线
        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", s):
            flush_para()
            out.append('<section style="margin:24px 0;border-top:1px dashed #e0dcd8;"></section>')
            continue

        # 有序 / 无序列表
        m = re.match(r"^(\d+)[.、]\s*(.+)$", s)
        if m:
            flush_para()
            out.append(
                '<section style="margin:0 0 12px;font-size:16px;line-height:1.8;color:%s;'
                'letter-spacing:0.5px;padding-left:26px;position:relative;">'
                '<span style="position:absolute;left:0;color:%s;font-weight:600;">%s.</span>%s</section>'
                % (TEXT, PRIMARY, m.group(1), _inline_md(m.group(2)))
            )
            continue

        m = re.match(r"^[-*•]\s*(.+)$", s)
        if m:
            flush_para()
            out.append(
                '<section style="margin:0 0 12px;font-size:16px;line-height:1.8;color:%s;'
                'letter-spacing:0.5px;padding-left:22px;position:relative;">'
                '<span style="position:absolute;left:4px;color:%s;">•</span>%s</section>'
                % (TEXT, PRIMARY, _inline_md(m.group(1)))
            )
            continue

        buf.append(s)

    flush_para()
    return "\n".join(out)


def build_page(title, body, subtitle=""):
    """完整可预览页面（浅色主题，离线可看）"""
    content = body_to_wechat_html(body)
    return """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>%s</title>
<style>
  body{margin:0;background:#f5f3f0;font-family:%s;}
  .wrap{max-width:680px;margin:0 auto;padding:36px 22px 60px;background:#fff;
        min-height:100vh;box-shadow:0 0 24px rgba(0,0,0,.05);}
  h1{font-size:22px;line-height:1.5;color:#222;margin:0 0 8px;letter-spacing:.5px;}
  .sub{font-size:13px;color:%s;margin:0 0 26px;padding-bottom:18px;
       border-bottom:1px solid #eee;letter-spacing:.5px;}
  .note{max-width:680px;margin:18px auto 0;padding:10px 14px;background:#fffaf0;
        border:1px solid #f0e2c8;border-radius:6px;font-size:12px;color:#8a6d3b;
        line-height:1.7;font-family:%s;}
</style></head>
<body>
<div class="wrap">
  <h1>%s</h1>
  <div class="sub">%s</div>
  %s
</div>
<div class="note">此页面为本地预览。要发到公众号，请在工具站里点「复制公众号 HTML」，
再到公众号编辑器里 Ctrl+V 粘贴——内联样式会一起带过去。</div>
</body></html>""" % (_esc(title), FONT_STACK, SUB, FONT_STACK, _esc(title), _esc(subtitle), content)


def draft_to_html(title, body, subtitle=""):
    """只返回可粘贴的片段（不含 <html> 外壳），用于直接粘进公众号编辑器"""
    return body_to_wechat_html(body)


if __name__ == "__main__":
    import io
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import db

    ds = db.list_drafts(limit=1)
    if not ds:
        print("没有草稿，先生成一篇")
        sys.exit(0)
    d = ds[0]
    frag = draft_to_html(d["title"], d["body"])
    p1 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "preview.html")
    io.open(p1, "w", encoding="utf-8").write(build_page(d["title"], d["body"], "本地预览 · " + (d.get("topic") or "")))
    print("wrote", p1)
    print("fragment len:", len(frag))
