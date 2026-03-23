#!/bin/bash

TODO="$HOME/projects/ssg/myblog/content/notes/todo.md"
NOTE="$HOME/projects/ssg/myblog/content/notes/note.md"
DATE=$(date '+%Y-%m-%d')

ACTION=$1

# 无 action 或非已知命令时默认 ta（不 shift，内容保留）
case $ACTION in
  ta|td|tr|na|nd|nr|ls) shift ;;
  *) ACTION="ta" ;;
esac
CONTENT="$@"

case $ACTION in
  ta)  # todo add: notes ta 日期 时间段 内容（日期可选，如: notes ta 09:00-10:00 加评论）
    if [[ "$1" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
      ENTRY_DATE="$1"; shift
    else
      ENTRY_DATE="$DATE"
    fi
    ENTRY_CONTENT="$@"
    ENTRY_LINE="- [ ] $ENTRY_DATE $ENTRY_CONTENT"
    sed -i '' "/## 待办/a\\
$ENTRY_LINE
" $TODO
    echo "📝 已添加：$ENTRY_LINE"
    ;;

  td)  # todo done: notes td 评论（模糊搜索，移到已完成）
    LINE=$(grep -n "\[ \].*$CONTENT" $TODO | head -1)
    if [ -z "$LINE" ]; then
      echo "❌ 找不到包含「$CONTENT」的待办"
      exit 1
    fi
    LINENUM=$(echo "$LINE" | cut -d: -f1)
    MATCHED=$(echo "$LINE" | cut -d: -f2-)
    DONE=$(echo "$MATCHED" | sed 's/\[ \]/[✓]/')
    sed -i '' "${LINENUM}d" $TODO
    sed -i '' "/## 完成/a\\
$DONE
" $TODO
    echo "✅ 已完成：$MATCHED"
    ;;

  na)  # note add: notes na 写篇 webhook 踩坑文章
    sed -i '' "/## 想法/a\\
- $DATE $CONTENT
" $NOTE
    echo "💡 已记录：$CONTENT"
    ;;

  nd)  # note done: notes nd webhook（模糊搜索，移到已实现）
    LINE=$(grep -n "^- .*$CONTENT" $NOTE | head -1)
    if [ -z "$LINE" ]; then
      echo "❌ 找不到包含「$CONTENT」的灵感"
      exit 1
    fi
    LINENUM=$(echo "$LINE" | cut -d: -f1)
    MATCHED=$(echo "$LINE" | cut -d: -f2-)
    sed -i '' "${LINENUM}d" $NOTE
    sed -i '' "/## 实现/a\\
$MATCHED
" $NOTE
    echo "✅ 已实现：$MATCHED"
    ;;

  tr)  # todo remove: notes tr 关键词（模糊搜索删除 todo，需确认）
    MATCHES=$(grep -n "$CONTENT" $TODO 2>/dev/null)
    if [ -z "$MATCHES" ]; then
      echo "❌ 找不到包含「$CONTENT」的待办"
      exit 1
    fi
    COUNT=$(echo "$MATCHES" | wc -l | tr -d ' ')
    echo "找到 $COUNT 条匹配："
    echo "$MATCHES" | while IFS= read -r line; do
      echo "  $line"
    done
    printf "确认删除？[y/N] "
    read -r CONFIRM
    if [[ "$CONFIRM" == "y" || "$CONFIRM" == "Y" ]]; then
      grep -n "$CONTENT" $TODO | cut -d: -f1 | sort -rn | while read -r n; do sed -i '' "${n}d" $TODO; done
      echo "🗑️  已删除 $COUNT 条"
    else
      echo "已取消"
    fi
    ;;

  nr)  # note remove: notes nr 关键词（模糊搜索删除 note，需确认）
    MATCHES=$(grep -n "$CONTENT" $NOTE 2>/dev/null)
    if [ -z "$MATCHES" ]; then
      echo "❌ 找不到包含「$CONTENT」的灵感"
      exit 1
    fi
    COUNT=$(echo "$MATCHES" | wc -l | tr -d ' ')
    echo "找到 $COUNT 条匹配："
    echo "$MATCHES" | while IFS= read -r line; do
      echo "  $line"
    done
    printf "确认删除？[y/N] "
    read -r CONFIRM
    if [[ "$CONFIRM" == "y" || "$CONFIRM" == "Y" ]]; then
      grep -n "$CONTENT" $NOTE | cut -d: -f1 | sort -rn | while read -r n; do sed -i '' "${n}d" $NOTE; done
      echo "🗑️  已删除 $COUNT 条"
    else
      echo "已取消"
    fi
    ;;

  ls)  # 列出待办
    echo "=== 待办 ==="
    grep '\[ \]' $TODO || echo "（空）"
    ;;

  *)
    echo "用法："
    echo "  notes ta [日期] <时间区间> <内容>  添加待办，如: notes ta 14:30-15:30 给博客加评论"
    echo "  notes td <关键词>                  完成待办（模糊搜索）"
    echo "  notes tr <关键词>                  删除待办（模糊搜索，需确认）"
    echo "  notes na <内容>                    记录灵感"
    echo "  notes nd <关键词>                  灵感已实现（模糊搜索）"
    echo "  notes nr <关键词>                  删除灵感（模糊搜索，需确认）"
    echo "  notes ls                           查看所有待办"
    ;;
esac
