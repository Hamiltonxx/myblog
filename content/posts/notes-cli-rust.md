+++
title = "有了 Claude Code，一天能做很多事——但想法怎么管？"
description = "从一个灵魂拷问出发：有了 CC 之后想法太多，怎么不让它们消失？记录了从设计 notes 系统、写 shell 脚本、到用 Rust 重写 CLI 的完整过程。"
date = 2026-03-23

[taxonomies]
categories = ["工具"]
tags = ["rust", "cli", "claude-code", "工具", "效率"]

[extra]
lang = "zh"
toc = true
+++

> 有了 Claude Code 之后，一天能做的事多了很多。但随之而来的问题是：想法、待办、灵感，冒出来的速度比消化的速度快。怎么办？

## 问题：想法管理

以前没有 CC 的时候，一天能做的事有限，想法不多，随手记在某个地方就行。

有了 CC 之后不一样了——一个下午可以同时推进好几件事，想法也跟着多起来。有些要写进博客分享，有些要做 reminder 提醒自己，有些是纯粹的灵感，过了就忘了。

问题来了：**怎样零摩擦地把这些东西记下来，又不引入新工具？**

## 方案：在博客里加 notes 目录

最轻量的做法是直接在已有的 Zola 博客里加一个 `notes/` 目录：

```
content/
  posts/     ← 正式博客
  notes/     ← 随手记
    todo.md  ← 待办
    note.md  ← 灵感
```

两个文件，职责分开：

- `todo.md`：有时间区间的待办，知道每件事花了多长时间
- `note.md`：灵感和想法，分已实现和未实现

在 `config.toml` 里把 notes 目录排除掉，不对外发布：

```toml
ignored_content = ["notes/**"]
```

## 文件格式设计

**todo.md**

```markdown
## 待办
- [ ] 2026-03-23 14:30-15:30 给博客加评论功能

## 已完成
- [✓] 2026-03-23 13:00-14:00 配好 webhook 自动部署
```

时间区间由自己输入，不是自动记录的。这样更灵活——可以提前记计划，也可以事后补记。

**note.md**

```markdown
## 想法

## 实现
```

## notes.sh：用 shell 管理这两个文件

格式定好之后，需要一个工具来操作它们。第一反应是 shell 脚本——最小依赖，Mac 和服务器都能用。

核心命令：

```bash
notes ta 2026-03-24 09:00-10:00 给博客加评论功能  # 添加待办（日期可选，默认今天）
notes td 评论                                      # 模糊搜索，移到已完成
notes tr 评论                                      # 模糊搜索，确认后删除
notes na 写篇 webhook 踩坑文章                     # 记录灵感
notes nd webhook                                   # 灵感已实现
notes nr webhook                                   # 删除灵感
notes ls                                           # 查看待办
```

几个细节值得说：

**日期可选**

`ta` 的日期可以省略，省略时用今天。这样既能提前排计划，也能快速记当下：

```bash
notes ta 09:00-10:00 买菜          # 今天
notes ta 2026-03-25 09:00-10:00 买菜  # 指定日期
```

**默认 ta**

不写子命令直接默认走 `ta`，少打几个字：

```bash
notes 09:00-10:00 买菜  # 等价于 notes ta 09:00-10:00 买菜
```

**td 的 bug**

`td` 原来用 `sed "/$MATCHED/d"` 删行，但 `$MATCHED` 里含有 `[ ]`，sed 把它当正则字符类处理，匹配不到原行，待办删不掉。

改用行号删除：

```bash
LINENUM=$(grep -n "$CONTENT" $TODO | head -1 | cut -d: -f1)
sed -i '' "${LINENUM}d" $TODO
```

同样的问题在 `nd`、`tr`、`nr` 里也有，一并修了。

---

## 用 Rust 重写

shell 脚本能用，但有个问题：**写完就忘**。过段时间回来看，不知道哪里有 bug，也不敢随便改。

趁着这个机会，用 Rust 重写成 CLI 工具。顺便搭了一个个人工具 workspace `cli-tools`，以后的小工具都往里放。

### workspace 结构

```
cli-tools/
├── Cargo.toml      # workspace 根
├── notes/          # notes CLI
└── todo-bg/        # 桌面壁纸生成（后面说）
```

根 `Cargo.toml`：

```toml
[workspace]
members = ["notes", "todo-bg"]
resolver = "2"
```

好处：共享 `target/` 编译缓存，`cargo build -p notes` 单独编译某个工具。

### clap 处理子命令

用 `clap` 的 derive 宏定义结构：

```rust
#[derive(Parser)]
#[command(name = "notes")]
struct Cli {
    #[command(subcommand)]
    cmd: Option<Cmd>,

    #[arg(trailing_var_arg = true)]
    args: Vec<String>,
}

#[derive(Subcommand)]
enum Cmd {
    Ta { args: Vec<String> },
    Td { keyword: Vec<String> },
    Tr { keyword: Vec<String> },
    // ...
    Ls,
}
```

`cmd: Option<Cmd>` 让子命令变成可选——`None` 时走默认 `ta` 逻辑，实现"不写子命令直接记待办"。

`#[derive(Parser)]` 是 clap 提供的宏，编译时自动给 `Cli` 生成 `parse()` 方法。clap 会把枚举变体名自动转成小写作为命令名，`Cmd::Ls` 对应命令行的 `ls`。

### ta 的日期判断

不用正则，直接看第一个参数格式：

```rust
fn is_date(s: &str) -> bool {
    let parts: Vec<&str> = s.split('-').collect();
    parts.len() == 3 && parts[0].len() == 4
}

fn cmd_ta(args: Vec<String>) {
    let today = Local::now().format("%Y-%m-%d").to_string();
    let (date, rest) = if is_date(&args[0]) {
        (args[0].clone(), args[1..].to_vec())
    } else {
        (today, args.clone())
    };
    let content = rest.join(" ");
    // ...
}
```

### td 用 flat_map 一次遍历

删除原行 + 插入到已完成，一次遍历搞定：

```rust
let new_content: String = content.lines()
    .flat_map(|l| {
        if l == matched {
            vec![]                        // 删除原行
        } else if l == "## 已完成" {
            vec!["## 已完成", &done]      // 插入
        } else {
            vec![l]
        }
    })
    .collect::<Vec<_>>()
    .join("\n");
```

`flat_map` = `map` + 压平一层。每个元素返回数组，空数组相当于删除，多个元素相当于插入。

---

## todo-bg：桌面壁纸跟着待办走

每 60 秒读一次 `todo.md`，当前时间在某任务的时间段内就显示任务名，否则显示今日完整日程。用 ImageMagick 生成图片，AppleScript 设置壁纸。

### 解析 bug

最初的解析逻辑写错了：

```rust
// 原来的写法
let parts: Vec<&str> = line.splitn(4, ' ').collect();
// 以为 parts[1] 是日期，实则：
// "- [ ] 2026-03-23 ..." → ["-", "[", "]", "2026-03-23 ..."]
// parts[1] = "["，不是日期，日期解析失败，所有任务都被跳过，返回 FREE
```

`- [ ] ` 里有空格，`splitn(4, ' ')` 前三个 slot 全被 `"-"` `"["` `"]"` 占掉了。

修法：先用 `"] "` 切掉前缀，再对剩余部分解析：

```rust
let Some(rest) = line.split_once("] ").map(|(_, r)| r) else { continue };
let parts: Vec<&str> = rest.splitn(3, ' ').collect();
// parts: ["2026-03-23", "09:00-10:00", "内容"]
```

### 磨玻璃壁纸

纯黑背景太单调，改成深色渐变 + 磨玻璃面板。ImageMagick 的实现思路：

1. 深色渐变背景
2. 克隆背景 → 高斯模糊 → 用圆角矩形 mask 裁出面板区域
3. 叠加半透明白色面板 + 高亮描边
4. 文字居中绘制

```rust
// 毛玻璃层：克隆背景 → 模糊 → mask 限定区域
"(".into(),
    "+clone".into(), "-blur".into(), "0x28".into(),
    "-alpha".into(), "set".into(),
    "(".into(),
        "-size".into(), format!("{}x{}", BG_W, BG_H),
        "xc:black".into(), "-fill".into(), "white".into(),
        "-draw".into(), rect.clone(),  // 圆角矩形
    ")".into(),
    "-compose".into(), "CopyOpacity".into(), "-composite".into(),
")".into(),
"-composite".into(),
```

字体用思源黑体 Light（`SourceHanSansSC-Light.otf`），日程模式左对齐、单任务模式居中。

---

## 部署

### notes → 系统命令

```bash
cargo build --release -p notes
cp target/release/notes /usr/local/bin/notes
```

之后在任意目录直接敲 `notes` 就能用。

### todo-bg → 开机自启（launchd）

先编译 release 版本：

```bash
cargo build --release -p todo-bg
cp target/release/todo-bg /usr/local/bin/todo-bg
```

创建 plist 文件 `~/Library/LaunchAgents/com.hamilton.todo-bg.plist`：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.hamilton.todo-bg</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/todo-bg</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
```

加载并启动：

```bash
launchctl load ~/Library/LaunchAgents/com.hamilton.todo-bg.plist
```

之后开机自动运行，崩溃了也会自动重启（`KeepAlive: true`）。
