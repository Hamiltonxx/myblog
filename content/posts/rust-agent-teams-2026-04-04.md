+++
title = "用 Rust 学 AI Agent——Day 10：一个 Claude 不够用，那就用两个"
description = "今天实现了 Agent Teams——主 agent 只负责协调，把写代码交给 coder，把审查交给 reviewer，每个 teammate 都是独立的 Claude 实例。这才是 multi-agent 的本质。"
date = 2026-04-04

[taxonomies]
categories = ["项目"]
tags = ["rust", "agent", "multi-agent", "tokio", "arc", "learn-agent-rust", "llm"]

[extra]
lang = "zh"
toc = true
+++

> Day 10，目标是让多个 agent 组成团队协作。
>
> 核心问题只有一个：**怎么让 Claude 管理其他 Claude？**
> 答案比你想的简单——一个工具调用，一个独立的 agent loop，一个不同的 system prompt。

---

## 为什么一个 agent 不够

做了前 9 天的 agent 开发后，我有一个越来越强烈的感受：**单个 agent 的问题不是能力，是注意力**。

给一个 agent 塞满工具、塞满上下文，它什么都能做——但它会把精力分散在所有事情上。就像让一个程序员既要写代码、又要审查代码、又要写文档、又要部署，每件事都做，但每件事都做不好。

真实的软件团队是怎么工作的？分工。

这就是 Agent Teams 的核心思想：**每个 agent 只做一件事，只持有做那件事所需的上下文。**

---

## 架构一句话

```
用户
  └─ 主 agent（协调者）
        └─ send_message("coder", "写一个 fibonacci 函数")
              └─ coder agent（独立 loop）→ 返回代码
        └─ send_message("reviewer", "审查这段代码: ...")
              └─ reviewer agent（独立 loop）→ 返回建议
  └─ 主 agent 综合两者，给用户最终答案
```

主 agent 不写代码，不审查代码——它只管「把任务分配给对的人」。

---

## 关键设计：Teammate 是什么

```rust
struct Teammate {
    name: String,
    role: String,
    system_prompt: String,  // ← 这是 teammate 的"灵魂"
}
```

`system_prompt` 决定了这个 teammate 的专长和行为。coder 的 system prompt 是：

> 你是一个 Rust 代码生成专家。收到需求后，直接给出简洁、正确的 Rust 代码实现，并简要说明思路。

reviewer 的是：

> 你是一个严格的代码审查专家。收到代码后，找出潜在的 bug、性能问题、不符合 Rust 惯用法的写法，给出具体的改进建议。

同样是 Claude，但因为 system prompt 不同，它们的「性格」完全不同——一个激进生产，一个挑剔审查。这就是 **prompt 作为角色定义** 的威力。

---

## send_message：主 agent 的唯一工具

主 agent 只暴露一个工具：`send_message`。

```rust
struct SendMessageTool {
    client: Arc<reqwest::Client>,
    api_key: Arc<String>,
    teammates: Arc<HashMap<String, Teammate>>,  // 注册表
}
```

当主 agent 决定要找 coder 帮忙时，它调用：

```json
{
  "to": "coder",
  "message": "写一个用迭代法计算 fibonacci(n) 的 Rust 函数"
}
```

工具的 `execute` 做三件事：

1. 从注册表里找到 `coder` 这个 Teammate
2. 用它的 `system_prompt` 启动一个**全新的 agent loop**（干净的 messages，完全隔离）
3. 等 loop 跑完，把最终文本结果返回给主 agent

```rust
async fn execute(&self, input: Value) -> String {
    let to = input["to"].as_str().unwrap_or("");
    let message = input["message"].as_str().unwrap_or("");

    let Some(teammate) = self.teammates.get(to) else {
        return format!("未找到队友: {}", to);
    };

    // teammate 的工具集（可以按角色定制）
    let mut tools: HashMap<String, Box<dyn Tool>> = HashMap::new();
    tools.insert("bash".to_string(), Box::new(BashTool));
    let tool_defs = tools.values().map(|t| t.definition()).collect::<Vec<_>>();

    // 独立的 agent loop，messages 完全隔离
    teammate_loop(
        &self.client, &self.api_key,
        &teammate.system_prompt,
        message,
        &tools, &tool_defs,
    ).await
}
```

---

## 上下文隔离是核心，不是细节

这一点值得单独说。

`teammate_loop` 和 s04 的 `agent_loop` 几乎一模一样，**区别只是 messages 是函数内的局部变量**：

```rust
async fn teammate_loop(/* ... */ task: &str /* ... */) -> String {
    let mut messages = vec![Message {    // ← 局部变量！
        role: "user".to_string(),
        content: json!(task),
    }];

    loop {
        // ... 标准 agent loop
    }
}
```

每次调用 `teammate_loop`，都是一个全新的对话历史。

为什么这很重要？想象一下反例：如果 coder 和 reviewer 共享同一个 messages 数组，coder 写代码时的所有推理过程（"我考虑了三种方案，最终选了这个"）都会出现在 reviewer 的上下文里。reviewer 会被 coder 的思路「污染」，更容易认同它而不是批判它。

**上下文隔离不只是工程实现，也是认知隔离。** 这是 multi-agent 的设计哲学。

---

## Arc 的用法：共享但不可变

注册表 `teammates` 同时被 main 和 SendMessageTool 持有：

```rust
let teammates = Arc::new(teammate_map);

tools.insert("send_message".to_string(), Box::new(SendMessageTool {
    teammates: teammates.clone(),   // Arc clone：引用计数 +1，数据不复制
    // ...
}));
```

`Arc`（Atomic Reference Counted）的语义：**多个所有者，但数据只有一份，且不可变**。

因为 teammates 注册表只读不写，不需要 `Mutex`，直接 `Arc<HashMap>` 就够了。`Arc::clone()` 只是增加引用计数，代价几乎为零。

---

## 主 agent 的 system prompt：协调者思维

```rust
let system = "你是一个技术团队的协调者。你有两个队友：
    - coder：负责写代码
    - reviewer：负责审查代码
    收到任务后，先让 coder 实现，再把代码发给 reviewer 审查，最后综合两人的结果给出完整回答。";
```

这里有一个微妙之处：主 agent 的 system prompt 告诉它**工作流程**，不只是工具列表。

"先让 coder 实现，再把代码发给 reviewer 审查"——这是协调模式，不是并发模式。主 agent 会串行地先等 coder 返回，然后把代码作为 message 发给 reviewer。这是用自然语言描述的工作流编排。

---

## 实际运行效果

```
任务> 帮我写一个计算斐波那契数列的 Rust 函数

[主agent 调用工具] send_message
[主agent -> coder(代码生成专家)] 写一个计算斐波那契数列的 Rust 函数
  [teammate 工具] bash  ← coder 运行了一下验证
[coder -> 主agent] 完成

[主agent 调用工具] send_message
[主agent -> reviewer(代码审查专家)] 请审查这段代码: fn fib(n: u64) -> u64 { ... }
[reviewer -> 主agent] 完成

Claude: 以下是完整实现和审查意见...
```

三层 agent，两次 API 调用链，但对用户来说只是一次对话。

---

## 和 s04 subagent 的区别

| | s04 subagent | s09 teammate |
|---|---|---|
| 身份 | 一次性任务执行者 | 持久的角色定义 |
| 触发 | 主 agent 认为需要时派发 | 用名字 send_message |
| system prompt | 通用助手 | 专属角色定义 |
| 适合 | 拆分独立子任务 | 专业分工协作 |

subagent 是「外包一个任务」，teammate 是「和一个专家合作」。

---

## 这个模式能扩展到哪里

现在的实现是串行的：主 agent 依次等 coder → reviewer。

但稍加修改，可以做到：

- **并发**：用 `tokio::spawn` 同时问多个 teammate，`join_all` 等结果
- **专业化工具集**：coder 有 write_file/bash，reviewer 只有 read_file，权限分离
- **链式协作**：coder 写 → tester 测 → reviewer 审，流水线
- **动态注册**：运行时 `register_teammate`，按需加入新专家

这些都是 Day 11（S10 Protocols）会触碰到的方向。

---

## 今天的 Rust 收获

| 概念 | 用在哪 |
|------|--------|
| `Arc<T>` | 多处共享 client、api_key、teammates 注册表 |
| `Arc<HashMap<K,V>>` | 只读共享数据，不需要 Mutex |
| `async fn` 嵌套 | `send_message.execute()` 内部 await `teammate_loop` |
| 函数局部 Vec | 用局部 `messages` 实现对话历史隔离 |

---

## 下一步

Day 11 是 S10 Protocols——给 agent 之间的通信加上统一的消息格式和状态机（enum 表示 Running/Idle/Shutdown），以及 `tokio::select!` 同时监听多个消息源。

从今天起，agent 不再是孤立的个体，而是真正的团队。

代码在：[https://github.com/Hamiltonxx/learn-claude-code-rust](https://github.com/Hamiltonxx/learn-claude-code-rust)
