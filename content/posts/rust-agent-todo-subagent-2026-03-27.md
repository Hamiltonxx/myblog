+++
title = "让 AI Agent 先列计划再干活——用 Rust 实现 TodoWrite 和 Subagent"
description = "两个让 agent 更可控的机制：强制规划的 TodoWriteTool，和消息完全隔离的子 agent。"
date = 2026-03-27

[taxonomies]
categories = ["项目"]
tags = ["rust", "ai-agent", "async", "tokio", "anthropic"]

[extra]
lang = "zh"
toc = true
+++

今天实现了 learn-agent-rust 的 S03 和 S04，一个让 agent 强制先规划再执行，另一个让主 agent 能派生独立的子 agent。

---

## S03：TodoWrite——用 system prompt 约束行为

核心思路很简单：实现一个 `TodoWriteTool`，然后在 system prompt 里写死规则——不列计划不许动手。

数据结构就是一个带状态的任务列表：

```rust
struct TodoItem {
    id: u32,
    title: String,
    status: String,  // "pending" | "in_progress" | "done"
}
```

`TodoWriteTool` 支持 `add / list / update / delete` 四个操作，通过 `input["action"]` 分发。

这里遇到一个 Rust 特有的问题：`Tool` trait 的 `execute` 是 `async fn`，但 `TodoManager` 需要可变引用。直接 `&mut self` 行不通，得用 `Arc<Mutex<T>>`：

```rust
struct TodoWriteTool {
    manager: Arc<Mutex<TodoManager>>,
}

// execute 里：
let mut mgr = self.manager.lock().unwrap();
```

`lock()` 拿到 `MutexGuard`，函数结束自动释放，简洁。

system prompt 的规则：

```
执行任何多步骤任务时必须：
1. 先用 todo_write(add) 把所有子任务列出
2. 开始某步前 update -> in_progress
3. 完成后 update -> done
```

测试："帮我创建一个 hello world Rust 项目并运行"，agent 乖乖先 add 了 4 个任务，再逐步执行，输出清晰可读：

```
⬜ [1] 创建项目目录结构
⬜ [2] 创建 Cargo.toml
⬜ [3] 创建 main.rs
⬜ [4] 运行项目
```

---

## S04：Subagent——消息完全隔离的子 agent

主 agent 有一个 `dispatch_agent` 工具，调用时会启动一个全新的 agent loop：

```rust
async fn agent_loop(
    client: &reqwest::Client,
    api_key: &str,
    task: &str,
    tools: &HashMap<String, Box<dyn Tool>>,
    tool_defs: &[Value],
) -> String
```

关键在于 `messages` 是这个函数的局部变量，从 `vec![user: task]` 开始，跑完整个 tool loop，最后把文本结果 return 给主 agent。主 agent 完全看不到子 agent 的中间过程，只收到最终结果。

`DispatchAgentTool` 持有 `client` 和 `api_key` 的 `Arc` 引用，`execute` 里创建子 agent 自己的工具集，然后调用 `agent_loop`：

```rust
struct DispatchAgentTool {
    client: Arc<reqwest::Client>,
    api_key: Arc<String>,
}
```

测试："帮我写两个文件，hello.txt 内容 hello，world.txt 内容 world"，主 agent 派发了两个子 agent 分别执行，互不干扰：

```
[主agent工具] dispatch_agent
[派生子agent] 任务: 创建 hello.txt，内容为 hello
  [子agent工具] write_file
[子agent完成]
[主agent工具] dispatch_agent
[派生子agent] 任务: 创建 world.txt，内容为 world
  [子agent工具] write_file
[子agent完成]
```

---

## 今天的 Rust 收获

- `Arc<Mutex<T>>`：async 环境下共享可变状态的标准做法
- trait object (`Box<dyn Tool>`) + `HashMap` 做动态分发，到这一步已经很顺手了
- 函数式隔离就是最简单的"进程隔离"——子 agent 的状态天然封闭在栈帧里

下一步是 S05 Skill Loading + S06 Context Compact，处理知识注入和上下文超长的问题。
