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
    return {
        'title':       fm_get('title'),
        'description': fm_get('description'),
        'category':    cats[0] if cats else '',
        'body':        body,
    }

# ── 主题配置 ─────────────────────────────────────────
ACCENT  = '#CE422B'                          # Rust 橙
FONT_ZH = '"Noto Sans SC","PingFang SC","Microsoft YaHei",sans-serif'
FONT_EN = '"JetBrains Mono","Fira Code",Consolas,monospace'
# ── 样式表 ────────────────────────────────────────────
S = {
    'h2':   f'font-family:{FONT_ZH};font-size:17px;font-weight:600;color:{ACCENT};'
            f'border-bottom:1px solid {ACCENT};padding-bottom:5px;margin:30px 0 10px;line-height:1.5;',
    'h3':   f'font-family:{FONT_ZH};font-size:15px;font-weight:600;color:#333;margin:20px 0 8px;line-height:1.5;',
    'p':    f'font-family:{FONT_ZH};font-size:14px;font-weight:400;line-height:1.9;'
            f'margin:10px 0;color:#3a3a3a;text-align:justify;letter-spacing:0.01em;',
    'bq':   f'border-left:3px solid {ACCENT};margin:14px 0;padding:8px 14px;'
            f'background-color:#fdf5f3;color:#666;font-family:{FONT_ZH};font-size:13px;',
    'th':   f'font-family:{FONT_ZH};font-size:13px;font-weight:500;'
            f'border:1px solid #e8e8e8;padding:7px 12px;background-color:#fdf5f3;text-align:left;',
    'td':   f'font-family:{FONT_ZH};font-size:13px;font-weight:400;'
            f'border:1px solid #e8e8e8;padding:7px 12px;color:#3a3a3a;',
    'hr':   'border:none;border-top:1px solid #f0f0f0;margin:28px 0;',
    'code': f'font-family:{FONT_EN};font-size:12px;color:{ACCENT};'
            f'background-color:#fdf5f3;padding:1px 5px;border-radius:3px;',
    'pre_td': f'background-color:#282c34;color:#abb2bf;padding:12px 14px;'
              f'border-radius:0 0 4px 4px;font-family:{FONT_EN};font-size:10px;'
              f'line-height:1.6;white-space:pre-wrap;word-break:break-all;',
    'pre_hdr': f'background-color:#21252b;padding:8px 14px;border-radius:4px 4px 0 0;',
    'pre_lang': f'font-family:{FONT_EN};font-size:11px;color:#636d83;letter-spacing:0.05em;',
}

# 列表样式
LI_WRAP   = 'display:flex;align-items:baseline;margin:5px 0;'
LI_BULLET = f'color:{ACCENT};font-size:16px;line-height:1.6;margin-right:8px;flex-shrink:0;'
LI_TEXT   = f'font-family:{FONT_ZH};font-size:14px;font-weight:400;line-height:1.85;color:#3a3a3a;flex:1;text-align:justify;'
OL_NUM    = f'font-family:{FONT_EN};color:{ACCENT};font-size:13px;font-weight:500;margin-right:8px;flex-shrink:0;line-height:1.85;min-width:16px;'

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
    return '<br>'.join(result.split('\n')).rstrip('<br>')

def _handle_code_blocks(html):
    def replace_block(m):
        lang_match = re.search(r'class="language-([^"\s]+)"', m.group(0))
        lang = lang_match.group(1) if lang_match else ''

        inner = m.group(2)
        inner = (inner.replace('&lt;', '<').replace('&gt;', '>')
                      .replace('&quot;', '"').replace('&#39;', "'")
                      .replace('&amp;', '&'))

        body = _highlight(inner.rstrip('\n'), lang)

        lang_tag = (f'<span style="float:right;{S["pre_lang"]}">{lang}</span>' if lang else '')
        header = (
            f'<td style="{S["pre_hdr"]}">'
            + lang_tag
            + f'<span style="color:#ff5f56;font-size:14px;margin-right:4px;">●</span>'
            f'<span style="color:#ffbd2e;font-size:14px;margin-right:4px;">●</span>'
            f'<span style="color:#27c93f;font-size:14px;">●</span>'
            f'</td>'
        )
        return (
            f'<table style="width:100%;margin:14px 0;border-collapse:collapse;">'
            f'<tr>{header}</tr>'
            f'<tr><td style="{S["pre_td"]}">{body}</td></tr>'
            f'</table>'
        )

    return re.sub(r'<pre><code([^>]*)>(.*?)</code></pre>', replace_block, html, flags=re.DOTALL)

def _convert_headings(html):
    # 微信会剥离 <h2>/<h3> 的 inline style，改用 <section>
    html = re.sub(r'<h2[^>]*>(.*?)</h2>',
                  lambda m: f'<section style="{S["h2"]}">{m.group(1)}</section>',
                  html, flags=re.DOTALL)
    html = re.sub(r'<h3[^>]*>(.*?)</h3>',
                  lambda m: f'<section style="{S["h3"]}">{m.group(1)}</section>',
                  html, flags=re.DOTALL)
    return html

def _convert_lists(html):
    def replace_ul(m):
        items = re.findall(r'<li[^>]*>(.*?)</li>', m.group(1), re.DOTALL)
        rows = ''.join(
            f'<section style="{LI_WRAP}">'
            f'<span style="{LI_BULLET}">•</span>'
            f'<span style="{LI_TEXT}">{item.strip()}</span>'
            f'</section>'
            for item in items
        )
        return f'<section style="margin:12px 0;">{rows}</section>'

    def replace_ol(m):
        items = re.findall(r'<li[^>]*>(.*?)</li>', m.group(1), re.DOTALL)
        rows = ''.join(
            f'<section style="{LI_WRAP}">'
            f'<span style="{OL_NUM}">{i}.</span>'
            f'<span style="{LI_TEXT}">{item.strip()}</span>'
            f'</section>'
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
                  f'<strong style="font-weight:500;color:#111;font-family:{FONT_ZH};">',
                  html)
    html = re.sub(r'<table>',
                  '<table style="width:100%;border-collapse:collapse;margin:16px 0;">',
                  html)
    return html

def md_to_html(md):
    import markdown
    # 不用 nl2br，避免段落内多余换行
    html = markdown.markdown(md, extensions=['fenced_code', 'tables'], output_format='html')
    return inject_styles(html)

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
    html = md_to_html(post['body'])

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
