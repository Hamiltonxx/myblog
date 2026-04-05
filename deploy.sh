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
