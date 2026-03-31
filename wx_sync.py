#!/Users/hamilton/projects/venv/bin/python
"""
wx_sync.py - 同步最新博客到微信公众号草稿箱（自动生成封面图）
用法:
  python3 wx_sync.py           # 自动选最新文章
  python3 wx_sync.py <文件路径>  # 指定文章
"""

import os
import re
import json
import glob
import sys
import textwrap
import requests
from pathlib import Path
from datetime import datetime

# ── 配置 ─────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
POSTS_DIR = BASE_DIR / 'content/posts'
TOKEN_CACHE = BASE_DIR / '.wechat_token'
COVER_PATH  = BASE_DIR / '.wx_cover.jpg'

FONT_ZH = '/System/Library/Fonts/STHeiti Medium.ttc'
FONT_EN = '/System/Library/Fonts/Supplemental/Arial.ttf'

def load_env():
    env_file = BASE_DIR / '.env'
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if '=' in line and not line.startswith('#'):
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip())

load_env()
APPID  = os.environ['WECHAT_APPID']
SECRET = os.environ['WECHAT_SECRET']

# ── 生成封面图 ────────────────────────────────────────
def generate_cover(title: str, category: str = '') -> Path:
    from PIL import Image, ImageDraw, ImageFont

    W, H = 900, 383   # 微信公众号封面推荐尺寸
    img = Image.new('RGB', (W, H))
    draw = ImageDraw.Draw(img)

    # 渐变背景：深蓝绿
    for y in range(H):
        t = y / H
        r = int(10  + t * 20)
        g = int(60  + t * 30)
        b = int(80  + t * 40)
        draw.line([(0, y), (W, y)], fill=(r, g, b))

    # 右侧装饰圆
    draw.ellipse([580, -80, 980, 320], fill=(255, 255, 255, 0), outline=(255,255,255,15), width=1)
    draw.ellipse([650, 200, 950, 500], fill=None, outline=(255,255,255,10), width=1)

    # 左侧绿色竖条
    draw.rectangle([50, 80, 57, H - 80], fill='#07C160')

    # 分类标签
    if category:
        try:
            cat_font = ImageFont.truetype(FONT_ZH, 22)
        except Exception:
            cat_font = ImageFont.load_default()
        draw.text((75, 90), f'#{category}', font=cat_font, fill='#07C160')

    # 标题（自动换行，最多两行）
    try:
        title_font = ImageFont.truetype(FONT_ZH, 44)
    except Exception:
        title_font = ImageFont.load_default()

    # 按字符宽度估算换行（每行约 16 个汉字）
    lines = textwrap.wrap(title, width=16)[:2]
    y = 145 if category else 130
    for line in lines:
        draw.text((75, y), line, font=title_font, fill='#FFFFFF')
        y += 60

    # 底部日期
    try:
        date_font = ImageFont.truetype(FONT_EN, 20)
    except Exception:
        date_font = ImageFont.load_default()
    today = datetime.now().strftime('%Y · %m · %d')
    draw.text((75, H - 65), today, font=date_font, fill='#aaaaaa')

    # 右下角 logo 文字
    try:
        logo_font = ImageFont.truetype(FONT_ZH, 20)
    except Exception:
        logo_font = ImageFont.load_default()
    draw.text((W - 130, H - 55), '曙辉智能', font=logo_font, fill='#07C160')

    img.save(str(COVER_PATH), 'JPEG', quality=92)
    return COVER_PATH

# ── Access Token ──────────────────────────────────────
def get_token():
    if TOKEN_CACHE.exists():
        cache = json.loads(TOKEN_CACHE.read_text())
        if cache.get('expires_at', 0) > datetime.now().timestamp() + 300:
            return cache['token']

    r = requests.get(
        'https://api.weixin.qq.com/cgi-bin/token',
        params={'grant_type': 'client_credential', 'appid': APPID, 'secret': SECRET},
        timeout=10
    )
    data = r.json()
    if 'access_token' not in data:
        raise RuntimeError(f"获取 token 失败: {data}")

    TOKEN_CACHE.write_text(json.dumps({
        'token': data['access_token'],
        'expires_at': datetime.now().timestamp() + data['expires_in']
    }))
    print("  access_token 已刷新")
    return data['access_token']

# ── 解析 Zola 文章 ────────────────────────────────────
def parse_post(filepath):
    text = Path(filepath).read_text(encoding='utf-8')
    m = re.match(r'^\+\+\+(.*?)\+\+\+(.*)', text, re.DOTALL)
    if not m:
        raise ValueError("无法解析 frontmatter")
    fm, body = m.group(1), m.group(2).strip()

    def fm_get(key):
        hit = re.search(rf'{key}\s*=\s*"(.+?)"', fm)
        return hit.group(1) if hit else ''

    def fm_list(key):
        hit = re.search(rf'{key}\s*=\s*\[(.+?)\]', fm, re.DOTALL)
        if not hit:
            return []
        return [x.strip().strip('"') for x in hit.group(1).split(',')]

    cats = fm_list('categories')
    date_hit = re.search(r'date\s*=\s*(\d{4}-\d{2}-\d{2})', fm)
    return {
        'title':       fm_get('title'),
        'description': fm_get('description'),
        'category':    cats[0] if cats else '',
        'tags':        fm_list('tags'),
        'date':        date_hit.group(1) if date_hit else '',
        'body':        body,
    }

# ── 设计 token（与 wx_rich_template.html 保持一致）─────
ACCENT   = '#CE4B16'
GRADIENT = 'linear-gradient(135deg,#CE4B16 0%,#E8621F 50%,#B03A0D 100%)'
FONT_BODY = '-apple-system,Helvetica,Arial,sans-serif'
FONT_MONO = 'monospace,sans-serif'
FONT_CODE = '"JetBrains Mono","Fira Code",Consolas,monospace'

# ── body 内各元素 inline style ─────────────────────────
S = {
    'p':      ('font-size:14.5px;font-weight:300;color:#333;line-height:1.85;'
               'margin:0 0 10px;padding:0;text-align:justify;'),
    'p_lead': ('font-size:14.5px;font-weight:300;color:#555;line-height:1.85;'
               'margin:0 0 24px;padding:0 0 0 12px;'
               f'border-left:3px solid {ACCENT};font-style:italic;'),
    'h2':     ('margin:0 0 14px;padding:0 0 0 10px;'
               f'border-left:3px solid {ACCENT};'
               'font-size:17px;font-weight:600;color:#1a1a1a;'
               'line-height:1.2;letter-spacing:0.02em;'),
    'h3':     (f'font-size:15px;font-weight:600;color:{ACCENT};margin:0 0 8px;padding:0;'),
    'bq':     ('margin:14px 0;padding:14px 16px;background:#FFF5F2;'
               f'border-left:3px solid {ACCENT};font-size:14.5px;color:#555;'
               'line-height:1.8;font-style:italic;border-radius:0 6px 6px 0;'),
    'code':   (f'font-family:{FONT_MONO};font-size:12.5px;background:#FFF0EA;color:#B03A0D;'
               'padding:2px 6px;border-radius:3px;border:1px solid #FADDD2;word-break:break-all;'),
    'hr':     'border:none;border-top:1px solid #ebebeb;margin:28px 0;',
    'th':     ('font-size:13px;font-weight:500;border:1px solid #e8e8e8;'
               'padding:7px 12px;background-color:#FFF0EA;text-align:left;'),
    'td':     ('font-size:13px;font-weight:300;border:1px solid #e8e8e8;'
               'padding:7px 12px;color:#3a3a3a;'),
}

def _highlight(code: str, lang: str) -> str:
    from pygments import highlight
    from pygments.lexers import get_lexer_by_name, TextLexer
    from pygments.formatters import HtmlFormatter
    try:
        lexer = get_lexer_by_name(lang) if lang else TextLexer()
    except Exception:
        lexer = TextLexer()
    fmt = HtmlFormatter(style='one-dark', nowrap=True, noclasses=True)
    result = highlight(code, lexer, fmt)
    return result.split('\n')

def _handle_code_blocks(html):
    def replace_block(m):
        lang_match = re.search(r'class="language-([^"\s]+)"', m.group(0))
        lang = lang_match.group(1) if lang_match else ''

        inner = m.group(2)
        inner = (inner.replace('&lt;', '<').replace('&gt;', '>')
                      .replace('&quot;', '"').replace('&#39;', "'")
                      .replace('&amp;', '&'))

        lines = _highlight(inner.rstrip('\n'), lang)
        code_html = ''.join(
            f'<span style="display:block;margin-bottom:3px;font-family:{FONT_CODE};'
            f'font-size:12.5px;line-height:1.7;color:#abb2bf;'
            f'white-space:pre-wrap;word-wrap:break-word;">{line}</span>'
            for line in lines if line
        )
        lang_tag = (f'<span style="float:right;font-family:{FONT_MONO};font-size:11px;'
                    f'color:#636d83;letter-spacing:0.08em;">{lang}</span>' if lang else '')
        dots = (
            '<span style="color:#ff5f56;font-size:16px;line-height:1;font-family:sans-serif;">●</span>'
            '<span style="color:#ffbd2e;font-size:16px;line-height:1;font-family:sans-serif;margin-left:4px;">●</span>'
            '<span style="color:#27c93f;font-size:16px;line-height:1;font-family:sans-serif;margin-left:4px;">●</span>'
        )
        return (
            f'<table width="100%" cellpadding="0" cellspacing="0" border="0" '
            f'style="background:#282c34;border-radius:6px;overflow:hidden;margin:14px 0;">'
            f'<tr><td style="background:#1d2026;padding:8px 14px;line-height:1;font-size:0;">'
            f'{lang_tag}{dots}</td></tr>'
            f'<tr><td style="padding:16px 18px;">{code_html}</td></tr>'
            f'</table>'
        )

    return re.sub(r'<pre><code([^>]*)>(.*?)</code></pre>', replace_block, html, flags=re.DOTALL)

def _convert_headings(html):
    # 微信会剥离 h2/h3 的 inline style，改用 section
    html = re.sub(r'<h2[^>]*>(.*?)</h2>',
                  lambda m: f'<section style="{S["h2"]}">{m.group(1)}</section>',
                  html, flags=re.DOTALL)
    html = re.sub(r'<h3[^>]*>(.*?)</h3>',
                  lambda m: f'<section style="{S["h3"]}">{m.group(1)}</section>',
                  html, flags=re.DOTALL)
    return html

def _convert_lists(html):
    p_li = ('font-size:14.5px;font-weight:300;color:#333;'
            'line-height:1.85;margin:0 0 7px;padding:0;')

    def replace_ul(m):
        items = re.findall(r'<li[^>]*>(.*?)</li>', m.group(1), re.DOTALL)
        rows = ''.join(
            f'<p style="{p_li}">◆&nbsp;&nbsp;<span>{item.strip()}</span></p>'
            for item in items
        )
        return f'<section style="margin:12px 0;">{rows}</section>'

    def replace_ol(m):
        items = re.findall(r'<li[^>]*>(.*?)</li>', m.group(1), re.DOTALL)
        rows = ''.join(
            f'<p style="{p_li}">'
            f'<span style="font-family:{FONT_MONO};color:{ACCENT};font-size:13px;'
            f'font-weight:500;margin-right:8px;">{i}.</span>'
            f'<span>{item.strip()}</span></p>'
            for i, item in enumerate(items, 1)
        )
        return f'<section style="margin:12px 0;">{rows}</section>'

    html = re.sub(r'<ul[^>]*>(.*?)</ul>', replace_ul, html, flags=re.DOTALL)
    html = re.sub(r'<ol[^>]*>(.*?)</ol>', replace_ol, html, flags=re.DOTALL)
    return html

def inject_styles(html):
    html = _handle_code_blocks(html)
    html = _convert_headings(html)
    html = _convert_lists(html)
    html = re.sub(r'<code>', f'<code style="{S["code"]}">', html)
    for tag, key in [('p', 'p'), ('th', 'th'), ('td', 'td')]:
        html = html.replace(f'<{tag}>', f'<{tag} style="{S[key]}">')
    html = html.replace('<blockquote>', f'<blockquote style="{S["bq"]}">')
    html = html.replace('<hr>', f'<hr style="{S["hr"]}">')
    html = re.sub(r'<strong>',
                  '<strong style="font-weight:600;color:#111;">',
                  html)
    html = re.sub(r'<table>',
                  '<table style="width:100%;border-collapse:collapse;margin:16px 0;">',
                  html)
    # 第一个 <p> 改为引言样式
    html = re.sub(r'<p style="[^"]*">', f'<p style="{S["p_lead"]}">', html, count=1)
    return html

def md_to_html(md):
    import markdown
    html = markdown.markdown(md, extensions=['fenced_code', 'tables'], output_format='html')
    return inject_styles(html)

# ── Header / Footer 构建 ──────────────────────────────
def build_header(title, tags, description, date, category=''):
    # 按 ：？，拆分标题为两行
    title_light, title_bold = title, ''
    for sep in ['：', '？', '，']:
        if sep in title:
            idx = title.index(sep)
            title_light = title[:idx + (1 if sep == '？' else 0)]
            title_bold  = title[idx + 1:] if sep != '？' else ''
            break

    # 顶部徽章：取分类 + 前两个 tag，大写
    badge_parts = ([category.upper()] if category else []) + [t.upper() for t in tags[:2]]
    tags_badge = ' · '.join(badge_parts[:3]) or 'BLOG'

    # tag pills
    pill = ('display:inline-block;background:rgba(255,255,255,0.13);'
            'border:1px solid rgba(255,255,255,0.25);color:rgba(255,255,255,0.85);'
            f'font-size:11px;padding:3px 10px;border-radius:3px;'
            f'font-family:{FONT_MONO};margin-right:6px;margin-bottom:6px;')
    tag_pills = ''.join(f'<span style="{pill}">{t}</span>' for t in tags)
    tag_pills += f'<span style="{pill}">{date}</span>'

    title_bold_html = (f'<p style="margin:0 0 14px;padding:0;font-size:19px;font-weight:700;'
                       f'color:#FFD4B8;line-height:1.45;">{title_bold}</p>' if title_bold else
                       '<p style="margin:0 0 14px;padding:0;"></p>')

    return (
        f'<table width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="background:{ACCENT};background:{GRADIENT};">'
        f'<tr><td style="padding:32px 20px 24px;">'
        f'<p style="margin:0 0 14px;padding:0;">'
        f'<span style="display:inline-block;background:rgba(255,255,255,0.15);'
        f'border:1px solid rgba(255,255,255,0.3);color:rgba(255,255,255,0.9);'
        f'font-size:11px;letter-spacing:0.1em;padding:4px 14px;border-radius:20px;'
        f'font-family:{FONT_MONO};">{tags_badge}</span></p>'
        f'<p style="margin:0 0 6px;padding:0;font-size:22px;font-weight:300;color:#fff;'
        f'line-height:1.45;letter-spacing:0.01em;">{title_light}</p>'
        f'{title_bold_html}'
        f'<p style="margin:0 0 18px;padding:0;font-size:13px;font-weight:300;'
        f'color:rgba(255,255,255,0.78);line-height:1.75;">{description}</p>'
        f'<p style="margin:0;padding:0;line-height:2;">{tag_pills}</p>'
        f'</td></tr></table>'
    )

def build_footer(blog_url='blog.cirray.cn'):
    return (
        f'<table width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="background:#f0ece8;">'
        f'<tr><td style="padding:24px 16px;text-align:center;">'
        f'<p style="color:#888;font-size:13px;line-height:1.8;margin:0;padding:0;">'
        f'<span style="color:{ACCENT};font-weight:600;">{blog_url}</span></p>'
        f'</td></tr></table>'
    )

# ── 上传永久素材（封面图）────────────────────────────
def upload_thumb(token, image_path):
    url = f'https://api.weixin.qq.com/cgi-bin/material/add_material?access_token={token}&type=image'
    with open(image_path, 'rb') as f:
        r = requests.post(url, files={'media': f}, timeout=30)
    data = r.json()
    if 'media_id' not in data:
        raise RuntimeError(f"上传封面失败: {data}")
    return data['media_id']

# ── 推草稿 ────────────────────────────────────────────
def push_draft(token, title, html, digest='', thumb_media_id=''):
    url = f'https://api.weixin.qq.com/cgi-bin/draft/add?access_token={token}'
    # 微信草稿标题实测上限约 37 字节
    def truncate_bytes(s, limit=36):
        encoded = s.encode('utf-8')
        if len(encoded) <= limit:
            return s
        return encoded[:limit].decode('utf-8', errors='ignore').rstrip()

    article = {
        'title':                 truncate_bytes(title),
        'content':               html,
        'digest':                digest.encode('utf-8')[:54].decode('utf-8', errors='ignore'),
        'content_source_url':    '',
        'need_open_comment':     0,
        'only_fans_can_comment': 0,
    }
    if thumb_media_id:
        article['thumb_media_id'] = thumb_media_id

    import json as _json
    body = _json.dumps({'articles': [article]}, ensure_ascii=False)
    r = requests.post(url, data=body.encode('utf-8'),
                      headers={'Content-Type': 'application/json; charset=utf-8'}, timeout=15)
    return r.json()

# ── 找最新文章 ────────────────────────────────────────
def latest_post():
    pattern = str(POSTS_DIR / '*-[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].md')
    posts = glob.glob(pattern)
    if not posts:
        raise FileNotFoundError("没找到带日期的文章")
    posts.sort(key=lambda p: (Path(p).stem[-10:], Path(p).stat().st_mtime))
    return posts[-1]

# ── 主流程 ────────────────────────────────────────────
def main():
    filepath = sys.argv[1] if len(sys.argv) > 1 else latest_post()
    print(f"文章: {Path(filepath).name}")

    post = parse_post(filepath)
    print(f"标题: {post['title']}")
    print(f"分类: {post['category']}")

    print("  生成封面图...")
    cover = generate_cover(post['title'], post['category'])
    print(f"  封面图: {cover}")

    print("  转换 Markdown...")
    header = build_header(post['title'], post['tags'], post['description'],
                          post['date'], post['category'])
    body   = md_to_html(post['body'])
    footer = build_footer()
    html = (
        '<div style="background:#f5f5f5;font-family:-apple-system,Helvetica,Arial,sans-serif;'
        'box-sizing:border-box;">'
        + header
        + '<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#fff;">'
        + '<tr><td style="padding:24px 16px 32px;word-wrap:break-word;">'
        + body
        + '</td></tr></table>'
        + footer
        + '</div>'
    )

    print("  获取 access_token...")
    token = get_token()

    print("  上传封面图...")
    thumb_id = upload_thumb(token, str(cover))
    print(f"  封面 media_id: {thumb_id}")

    print("  推送草稿...")
    result = push_draft(token, post['title'], html, post['description'], thumb_id)

    if 'media_id' in result:
        print(f"\n✓ 草稿已推送！")
        print(f"  draft media_id: {result['media_id']}")
        print(f"→ 去公众号后台发布: https://mp.weixin.qq.com")
    else:
        print(f"\n✗ 推送失败: {result}")
        sys.exit(1)

if __name__ == '__main__':
    main()
