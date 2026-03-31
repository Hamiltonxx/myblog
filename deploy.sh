#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

zola build

git add .

echo -n "提交信息（直接回车则用时间戳）: "
read msg

if [ -z "$msg" ]; then
    msg="deploy: $(date '+%Y-%m-%d %H:%M')"
fi

git commit -m "$msg"
git push

echo "✅ 发布完成！"

# ── 微信公众号同步 ─────────────────────────────────────
echo ""
echo -n "是否同步到微信公众号草稿？[y/N] "
read wx

if [[ "$wx" =~ ^[Yy]$ ]]; then
    echo -n "指定文章路径（直接回车则自动选最新）: "
    read wxfile
    if [ -z "$wxfile" ]; then
        /Users/hamilton/projects/venv/bin/python "$SCRIPT_DIR/wx_sync.py"
    else
        /Users/hamilton/projects/venv/bin/python "$SCRIPT_DIR/wx_sync.py" "$wxfile"
    fi
fi
