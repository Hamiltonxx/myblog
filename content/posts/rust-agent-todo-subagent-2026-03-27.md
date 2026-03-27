+++
title = "用 Rust 学 AI Agent——Day 4：让 Agent 先想后做，还能分身"
description = "两个机制让 agent 从「能干活」变成「有条理地干活」：TodoWrite 强制规划，Subagent 隔离执行——关键都在 Rust 的所有权设计上。"
date = 2026-03-27

[taxonomies]
categories = ["项目"]
tags = ["rust", "ai", "claude", "agent", "learn-agent-rust", "async", "arc-mutex"]

[extra]
lang = "zh"
toc = true
+++

> Day 3 之后，agent 能读文件、跑命令、改代码了。
>
> 但它是个急性子——任务一来直接上手，没有规划，没有进度，出了问题不知道卡在哪。
>
> 今天解决两件事：**让它先想再做**（S03），**让它能分身派活**（S04）。

---

## S03：system prompt 就是代码

### 先理解问题

Day 3 的 agent 拿到任务会直接调工具。你问它"帮我创建一个 Rust 项目并运行"，它可能直接跑 `cargo new`，跑完告诉你"好了"——中间过程你完全看不到，也不知道它做了几步、哪步失败了。

S03 要解决的是：**给 agent 装上规划意识**。

做法很直接——给它一个 `TodoWriteTool`，然后在 system prompt 里写死规则：

```
执行任何多步骤任务时必须：
1. 先用 todo_write(add) 把所有子任务列出
2. 开始某步前 update -> in_progress
3. 完成后 update -> done
```

这是 S03 最重要的洞察：**system prompt 本身就是约束代码**，不需要任何 if/else，用自然语言写规则，模型会遵守。

### Rust 实现的关键：Arc<Mutex<T>>

数据结构很简单：

```rust
struct TodoItem {
    id: u32,
    title: String,
    status: String,  // "pending" | "in_progress" | "done"
}

struct TodoManager {
    todos: Vec<TodoItem>,
    next_id: u32,
}
```

麻烦在 `TodoWriteTool`。`Tool` trait 的 `execute` 是 `async fn`，但 `TodoManager` 需要可变访问——在 async 环境里，你没办法直接持有 `&mut TodoManager`（借用生命周期和 async 不兼容）。

解法是 `Arc<Mutex<T>>`：

```rust
struct TodoWriteTool {
    manager: Arc<Mutex<TodoManager>>,
}

// execute 里：
async fn execute(&self, input: Value) -> String {
    let mut mgr = self.manager.lock().unwrap(); // 拿到 MutexGuard
    // ... 操作 mgr
    // 函数结束，MutexGuard 自动 drop，锁自动释放
}
```

- `Arc`：引用计数，允许多处持有同一个 manager
- `Mutex`：保证同一时刻只有一个 async 任务在改数据
- `lock().unwrap()`：拿到独占访问权，作用域结束自动归还

`execute` 里按 `input["action"]` 分发四个操作：

```rust
match input["action"].as_str().unwrap_or("") {
    "add"    => { let id = mgr.add(title); format!("已添加 #{}: {}", id, title) }
    "list"   => mgr.list(),
    "update" => mgr.update(id, status),
    "delete" => mgr.delete(id),
    other    => format!("未知操作: {}", other),
}
```

### 跑起来看效果

输入："帮我创建一个 hello world Rust 项目并运行"

```
[工具] todo_write  {"action":"add","title":"创建 Rust 项目目录结构"}
[工具] todo_write  {"action":"add","title":"创建 Cargo.toml 文件"}
[工具] todo_write  {"action":"add","title":"创建 main.rs 文件"}
[工具] todo_write  {"action":"add","title":"运行项目"}
[工具] todo_write  {"action":"update","id":1,"status":"in_progress"}
[工具] bash        {"command":"mkdir -p hello_world/src"}
[工具] todo_write  {"action":"update","id":1,"status":"done"}
...
[工具] bash        {"command":"cd hello_world && cargo run"}
[结果] Hello, World!
```

agent 严格遵守了规则——没有 if/else 强制，纯靠 system prompt。

---

## S04：隔离 = 局部变量

### 先理解问题

有时候一个任务可以拆成几个完全独立的子任务并行处理。比如"写三个模块"，没必要串行——派三个 agent 各干各的效率更高。

更重要的是**隔离**：子任务不应该看到主任务的对话历史，主任务也不应该被子任务的中间步骤污染。

### 核心实现：agent_loop 函数

S04 的关键洞察：**子 agent 的消息历史天然就是局部变量**。

把 agent loop 抽成一个函数：

```rust
async fn agent_loop(
    client: &reqwest::Client,
    api_key: &str,
    task: &str,
    tools: &HashMap<String, Box<dyn Tool>>,
    tool_defs: &[Value],
) -> String {
    // messages 是局部变量——和调用方完全无关
    let mut messages = vec![Message {
        role: "user".to_string(),
        content: json!(task),
    }];

    loop {
        let response = call_api(client, api_key, &messages, tool_defs, "你是一个能干的助手。").await;

        if response.stop_reason.as_deref() == Some("tool_use") {
            // ... 执行工具，追加历史
        } else {
            // 返回子 agent 的最终文本
            return collect_text(&response.content);
        }
    }
}
```

`messages` 在函数栈帧上，函数返回就消失。主 agent 只看到 `String` 类型的最终结果，子 agent 的全部中间步骤对它不可见——隔离是 Rust 的默认行为，不需要特殊设计。

### DispatchAgentTool：让主 agent 能派活

```rust
struct DispatchAgentTool {
    client: Arc<reqwest::Client>,  // Arc 共享，避免重复创建
    api_key: Arc<String>,
}
```

`execute` 里：创建子 agent 自己的工具集，调用 `agent_loop`：

```rust
async fn execute(&self, input: Value) -> String {
    let task = input["task"].as_str().unwrap_or("").to_string();

    let mut sub_tools: HashMap<String, Box<dyn Tool>> = HashMap::new();
    sub_tools.insert("bash".to_string(),       Box::new(BashTool));
    sub_tools.insert("write_file".to_string(), Box::new(WriteFileTool));
    // ...

    let sub_tool_defs: Vec<Value> = sub_tools.values().map(|t| t.definition()).collect();

    // 调用独立 loop，阻塞等待结果
    agent_loop(&self.client, &self.api_key, &task, &sub_tools, &sub_tool_defs).await
}
```

注意 `client` 和 `api_key` 用 `Arc` 共享——因为主 agent 和所有子 agent 都要用，但不需要各自持有一份拷贝。

### 跑起来看效果

输入："帮我写两个文件：hello.txt 内容 hello，world.txt 内容 world"

```
[主agent工具] dispatch_agent
[派生子agent] 任务: 创建 hello.txt，内容为 hello
  [子agent工具] write_file
[子agent完成]

[主agent工具] dispatch_agent
[派生子agent] 任务: 创建 world.txt，内容为 world
  [子agent工具] write_file
[子agent完成]

Claude: 两个文件都已创建完成。
```

主 agent 只看到两次 `dispatch_agent` 的结果，子 agent 的内部过程完全封装在 `agent_loop` 里。

---

## 今天的 Rust 收获

| 机制 | 用在哪 | 解决什么问题 |
|------|--------|-------------|
| `Arc<Mutex<T>>` | TodoWriteTool | async 环境下共享可变状态 |
| 函数局部变量 | agent_loop 的 messages | 子 agent 天然隔离 |
| `Arc<Client>` | DispatchAgentTool | 多 agent 共享 HTTP 客户端 |

S03 让我意识到：**system prompt 的约束力不亚于代码里的 if/else**，而且更灵活——改规则不用重新编译。

---

## 下一步

Day 5：S05 Skill Loading（按需注入知识，不把所有 prompt 塞进 system）+ S06 Context Compact（消息超过 20 条时自动压缩，防止上下文爆炸）。

代码在：[https://github.com/Hamiltonxx/learn-claude-code-rust](https://github.com/Hamiltonxx/learn-claude-code-rust)
