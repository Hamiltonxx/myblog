+++
title = "让 AI 每天出一道 Rust 题：用 Claude Remote Agent 实现自动刷题"
description = "不是刷 LeetCode，而是让 AI 读你的真实项目代码、每天定时出一道针对性练习题，push 到 GitHub 等你去做。"
date = 2026-03-30

[taxonomies]
categories = ["工具"]
tags = ["rust", "claude-code", "remote-agent", "github", "automation"]

[extra]
lang = "zh"
toc = true
+++

今天搭了一套自动出题系统：Claude Remote Agent 每天 18:00 读我两个 Rust 工程的最新 commit，结合预设考点计划，自动生成一道练习题 push 到 GitHub，我 pull 下来做就行。

---

## 为什么要这么搞

我有两个 Rust 工程一直在推进：

- **cbase**：RAG 向量搜索 + MCP Server，用了 fastembed、qdrant、tokio、Arc/Mutex
- **learn-claude-code-rust**：用 Rust 实现 Claude API agent loop，有 async trait、serde tag enum、reqwest

代码写了不少，但很多 Rust 特性是"用过但没真正掌握"——比如 `Arc<Mutex<T>>` 在 async 里怎么用对、`impl Display` 怎么写、`#[serde(tag)]` 背后是什么。

与其去刷通用题，不如直接从自己的代码里出题，练的都是真实遇到的模式。

---

## 架构设计

```
每天 18:00
  │
  ▼
Remote Agent（Anthropic 云端）
  ├── gh api 读 learn-claude-code-rust 最新 commit diff（只读，不 clone）
  ├── gh api 读 cli-tools 最新 commit diff（只读，不 clone）
  ├── clone rust-daily-quiz（写入用）
  ├── 按考点计划选题，结合代码改动出题
  ├── 写入 quiz/src/quiz_NNN.rs
  ├── 更新 quiz/QUIZ.md
  └── commit + push

用户：git pull → cargo run --bin quiz_NNN
```

关键设计决策：**只 clone rust-daily-quiz**（要写入的 repo），另外两个工程用 `gh api` 只读，不 clone。Remote Agent 每次启动是全新容器，clone 小 repo 开销极低。

---

## Agent Prompt 设计

Prompt 需要完全自包含，agent 启动时没有任何上下文。核心步骤：

**1. 检查最近代码变动**

用 `gh api` 查两个 repo 最近的 commit，找出改动的 `.rs` 文件：

```bash
gh api "repos/Hamiltonxx/learn-claude-code-rust/commits?per_page=3"
gh api "repos/Hamiltonxx/cli-tools/commits?per_page=3"
```

对最新 commit 查看 diff，聚焦 `files[].patch` 中 `.rs` 文件的改动内容。

**2. 确定下一题编号和已覆盖考点**

在已 clone 的 rust-daily-quiz 目录中，列出 `quiz/src/quiz_*.rs`，找最大编号，读 `QUIZ.md` 了解已覆盖考点。

**3. 按考点计划选题**

```
trait 实现(Display/Debug) → enum+match → Arc<Mutex<T>> →
serde进阶 → async trait → 自定义Error → 结构体生命周期 →
From/Into → 泛型+trait bound(Send+Sync) → newtype pattern
```

结合代码改动选最相关的考点，若无明显变动则按序选下一个。

**4. 题目格式**

```rust
// ============================================================
// Quiz NNN — 考点标题
// 日期: YYYY-MM-DD  难度: ★★☆☆☆  考点: xxx
// 灵感: 工程名/文件路径（具体代码片段说明）
// ============================================================
//
// 背景：[考点在实际代码中如何出现]
// 任务：[清晰的任务描述]
// 运行：cargo run --bin quiz_NNN

// starter code with TODO

fn main() { /* test cases */ }

// ============================================================
// 期望输出：...
// 提示：...
// ============================================================
```

**5. 写入文件、更新 QUIZ.md、commit + push**

---

## Token 效率问题

搭建过程中踩了个坑：第一次探索两个工程花了 2K+ token，如果每天重复扫描代价太高。

解决方案：**把稳定信息存入 Claude memory，不稳定信息用 git diff 增量读。**

memory 里存：
- 用户 Rust 水平评估（稳定）
- 两个工程路径和关键文件映射（稳定）
- 下一题编号（append-only）

每次出题只需读 1~2 个目标文件，而不是全量扫描。这个优化适用于本地 session，Remote Agent 本身是无状态的，靠 QUIZ.md 维护进度。

---

## Remote Agent 是什么

CCR（Cloud Code Runner）是 Anthropic 云端运行的 Claude Code 实例。

简单说：**就是一个跑在云上的 Claude Code session，按时间自动触发。**

```
你的机器                    Anthropic 云端

定时触发（18:00）  ──────►  新容器启动
                            clone repo
                            运行 Claude
                            执行工具（Bash/Write/gh...）
                            commit + push
                            容器销毁
```

和你本地用 Claude Code 是同一个东西，区别是：
- 不需要你的机器在线
- 每次全新环境，无状态
- 通过 GitHub repo 交换结果

用 `/schedule` skill 配置，支持标准 cron 表达式，最小间隔 1 小时。

---

## 为什么不用本地 cron

也想过用 `launchd` + `claude -p` 在本地跑，优势是能直接读本地 memory 文件，context 更丰富。

但 Remote Agent 更省心：机器关机也不影响，结果通过 GitHub 同步，哪台设备都能 pull。对于"每天一题"这个场景，无状态反而合适——每次都是全新出发，不依赖历史 session。

---

## 结果

- GitHub repo：[rust-daily-quiz](https://github.com/Hamiltonxx/rust-daily-quiz)
- 每天 18:00 自动出题，写入 `quiz/src/quiz_NNN.rs`
- 管理页面：https://claude.ai/code/scheduled

今天 18:00 第一题，考点是 **trait 实现（Display/Debug）**，灵感来自 `search.rs` 里手动拼装搜索结果输出那段代码。

下一步打算：做完题把答案也 push 上去，顺便看看 agent 出的题质量怎么样，必要时调整 prompt。
