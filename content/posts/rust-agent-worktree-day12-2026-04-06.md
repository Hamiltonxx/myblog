+++
title = "用 Rust 学 AI Agent——Day 12：两个 Agent 把对方文件覆盖了，git worktree 三行解决"
description = "多 Agent 并发写文件会互相覆盖，worktree 隔离是最简单的解法——顺便今天把 12 天的 Rust Agent 框架全合进了一个文件，收官。"
date = 2026-04-06

[taxonomies]
categories = ["项目"]
tags = ["rust", "ai-agent", "concurrency", "worktree", "tokio", "pathbuf"]

[extra]
lang = "zh"
toc = true
+++

今天是 [learn-agent-rust](https://github.com/Hamiltonxx/learn-claude-code-rust) 的第 12 天，也是最后一个技术 session。做了两件事：让多个 AI Agent 不再互相踩脚，然后把前 11 天写的所有机制合进了一个文件。

---

## 问题：两个 Agent 写文件会打架

想象这个场景——

你启动了两个 AI Agent 同时干活：一个写代码，一个做代码审查。它们都勤勤恳恳，但都往同一个目录写文件，结果：

```
# coder 写了
output.txt → "fn hello() { println!(\"Hello\") }"

# reviewer 紧跟着写
output.txt → "# 审查意见：缺少注释"

# coder 的成果：消失了
```

这不是假设，是真实会发生的 race condition。文件系统不像数据库，没有事务，后写的直接覆盖前面的。

---

## git worktree 是什么

`git worktree` 是 Git 自带的一个功能，很多人没用过。

通常你只有一个工作目录：

```
my-repo/     ← 只能在这一个地方工作
  .git/
  src/
```

用 worktree 之后，同一个仓库可以同时 checkout 到多个目录，**各自独立，共享同一个 `.git`**：

```bash
git worktree add ../my-repo-coder    -b coder-work
git worktree add ../my-repo-reviewer -b reviewer-work
```

```
my-repo/          ← main 分支
my-repo-coder/    ← coder 在这里工作，独立分支
my-repo-reviewer/ ← reviewer 在这里工作，独立分支
```

每个 Agent 待在自己的目录里，写什么文件都不会影响别人，最后再 merge 回主分支。

---

## 在 Rust 里怎么实现

核心改动只有一处：给工具加一个 `cwd: PathBuf` 字段，执行命令时用 `.current_dir()` 限定范围。

```rust
struct BashTool {
    cwd: PathBuf,  // 这个 Agent 专属的工作目录
}

impl Tool for BashTool {
    async fn execute(&self, input: Value) -> String {
        std::process::Command::new("sh")
            .arg("-c")
            .arg(input["command"].as_str().unwrap_or(""))
            .current_dir(&self.cwd)   // ← 命令只在自己的目录里跑
            .output()
            // ...
    }
}
```

启动 Agent 时各给一个独立目录：

```rust
let coder_dir    = temp_dir().join("worktree/coder");
let reviewer_dir = temp_dir().join("worktree/reviewer");
std::fs::create_dir_all(&coder_dir).unwrap();
std::fs::create_dir_all(&reviewer_dir).unwrap();

tokio::spawn(teammate_worker("coder",    coder_dir, ...));
tokio::spawn(teammate_worker("reviewer", reviewer_dir, ...));
```

不一定要用真正的 `git worktree` 命令——临时目录效果完全一样，而且简单很多。真正生产级别的场景才需要 git worktree，因为那样每个 Agent 的改动都有完整 git 历史，方便 review 和合并。

---

## 最后的 s_full.rs：12 个机制，一个文件

12 天写了 12 个独立的 session 文件，今天最后的任务是把它们全部组合进 `s_full.rs`，端到端跑通。

| 机制 | 作用 |
|------|------|
| S01 agent loop | 对话记忆，多轮交互 |
| S02 tool dispatch | `HashMap<String, Box<dyn Tool>>` 动态分发 |
| S03 TodoManager | 先列计划再执行 |
| S04 subagent | 独立 messages，子任务隔离 |
| S05 skill loading | 按需从文件注入知识 |
| S06 context compact | 超 20 条消息自动压缩成摘要 |
| S07 task system | 依赖拓扑排序，按序执行 |
| S08 background tasks | `tokio::spawn` + `mpsc` 后台通知 |
| S09 agent teams | 多 teammate 并发协作 |
| S10 protocols | 统一消息格式 + shutdown 协议 |
| S11 autonomous | teammate 自主扫描任务板，自动认领 |
| S12 worktree | 每个 teammate 独立 CWD，不打架 |

跑起来的效果：

```
=== s_full — 12 个机制综合演示 ===
[coder] 上线 | 目录: /tmp/s_full_worktree/coder
[reviewer] 上线 | 目录: /tmp/s_full_worktree/reviewer

用户> 帮我写一个冒泡排序的 Rust 实现，然后让人审查一下

[工具] add_board_task
[工具] add_board_task
Agent: 已分配两个任务：coder 写实现，reviewer 负责审查。

[coder] 认领 #1: 用 Rust 实现冒泡排序
[reviewer] 认领 #2: 审查冒泡排序代码
[后台通知] [coder] 完成任务 #1
[后台通知] [reviewer] 完成任务 #2
```

两个 Agent 各自在自己的目录里工作，主 Agent 继续和用户对话，后台通知实时弹出——整个系统是活的。

---

## 12 天学到的最重要的事

做这个项目之前，我对"AI Agent"的理解停留在"调 API 拿回答"。12 天之后才明白，Agent 的核心根本不是 AI，而是**围绕 AI 的那一套工程结构**：

- 怎么让它记住上下文（消息列表）
- 怎么让它使用工具（tool dispatch）
- 怎么让多个它协作（任务板 + channel）
- 怎么让它不崩溃（压缩、隔离、shutdown）

Rust 在这里的价值也很真实——不是因为"快"，而是 `Arc<Mutex<T>>`、`mpsc`、`PathBuf`、`async/await` 这些原语让并发协作的结构变得**显式且可信赖**。编译器会阻止你写出竞争条件，而不是等到 runtime 翻车。

---

## 下一步

- Day 13：改网站，把源码展示从 Python 换成 Rust
- Day 14：发布，去 r/rust 和 V2EX 讲讲这个项目

项目地址：[github.com/Hamiltonxx/learn-claude-code-rust](https://github.com/Hamiltonxx/learn-claude-code-rust)
