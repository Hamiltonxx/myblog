+++
title = "用 Rust 学 AI Agent——Day 3：让 Agent 真正能干活（工具分发）"
description = "从硬编码 bash 到 HashMap 动态分发：一个 Rust trait object 的实战，理解 AI Agent 工具系统的核心原理。"
date = 2026-03-26

[taxonomies]
categories = ["项目"]
tags = ["rust", "ai", "claude", "agent", "learn-agent-rust", "trait", "async"]

[extra]
lang = "zh"
toc = true
+++

> Day 3 之前，agent 能聊天，但只能"想"，不能"做"。
>
> 今天之后，它能读文件、写文件、改文件、跑命令——而且以后加新工具，不用动任何已有代码。

---

## 先理解问题

Day 1 的 S01 跑通了 agent loop——模型记住了上下文，能连续对话。但它只会说话，碰到"帮我读一下 Cargo.toml"这种任务，只能干瞪眼，因为它没有任何操作文件系统的能力。

S02 要解决的就是这个：**给 agent 装上工具**。

但装工具有两种方式：

**方式 A（笨办法）：**

```rust
if tool_name == "bash" {
    run_bash(input)
} else if tool_name == "read_file" {
    run_read(input)
} else if tool_name == "write_file" {
    // ...
}
```

每加一个工具改一次 if/else，维护噩梦。

**方式 B（S02 的做法）：**

```rust
tools["read_file"].execute(input).await
```

一行查表，不管有多少工具，agent loop 一字不改。

---

## Rust 实现的核心：trait object

要让"一行查表"成为可能，需要 Rust 的 trait object。

### 第一步：定义 Tool trait

在 `lib.rs` 里，给所有工具规定一个统一的接口：

```rust
use async_trait::async_trait;

#[async_trait]
pub trait Tool: Send + Sync {
    fn name(&self) -> &str;
    fn definition(&self) -> Value; // 告诉 Claude 这个工具叫什么、参数长什么样
    async fn execute(&self, input: Value) -> String;
}
```

三个方法：
- `name()`：工具的名字，Claude 调用时用这个匹配
- `definition()`：返回 JSON Schema，告诉 Claude 这个工具能做什么、需要什么参数
- `execute()`：真正干活的地方

`async_trait` 是一个 crate，因为 Rust 的 trait 原生不支持 async 方法，它帮你做了转换。

### 第二步：实现 4 个工具

**BashTool**——执行 shell 命令：

```rust
struct BashTool;

#[async_trait]
impl Tool for BashTool {
    fn name(&self) -> &str { "bash" }

    fn definition(&self) -> Value {
        json!({
            "name": "bash",
            "description": "Run a bash command",
            "input_schema": {
                "type": "object",
                "properties": {
                    "command": { "type": "string" }
                },
                "required": ["command"]
            }
        })
    }

    async fn execute(&self, input: Value) -> String {
        let command = input["command"].as_str().unwrap_or("");
        let output = Command::new("sh").arg("-c").arg(command).output().unwrap();
        String::from_utf8_lossy(&output.stdout).to_string()
            + &String::from_utf8_lossy(&output.stderr)
    }
}
```

**ReadFileTool**——读文件：

```rust
async fn execute(&self, input: Value) -> String {
    let path = input["path"].as_str().unwrap_or("");
    std::fs::read_to_string(path).unwrap_or_else(|e| e.to_string())
}
```

**WriteFileTool**——写文件：

```rust
async fn execute(&self, input: Value) -> String {
    let path = input["path"].as_str().unwrap_or("");
    let content = input["content"].as_str().unwrap_or("");
    std::fs::write(path, content)
        .map(|_| "ok".to_string())
        .unwrap_or_else(|e| e.to_string())
}
```

**EditFileTool**——替换文件中的字符串：

```rust
async fn execute(&self, input: Value) -> String {
    let path = input["path"].as_str().unwrap_or("");
    let old = input["old_str"].as_str().unwrap_or("");
    let new = input["new_str"].as_str().unwrap_or("");
    match std::fs::read_to_string(path) {
        Ok(text) => {
            let updated = text.replace(old, new);
            std::fs::write(path, updated)
                .map(|_| "ok".to_string())
                .unwrap_or_else(|e| e.to_string())
        }
        Err(e) => e.to_string(),
    }
}
```

### 第三步：HashMap 分发

把所有工具装进一个 HashMap：

```rust
let mut tools: HashMap<String, Box<dyn Tool>> = HashMap::new();
tools.insert("bash".to_string(),       Box::new(BashTool));
tools.insert("read_file".to_string(),  Box::new(ReadFileTool));
tools.insert("write_file".to_string(), Box::new(WriteFileTool));
tools.insert("edit_file".to_string(),  Box::new(EditFileTool));
```

`Box<dyn Tool>` 是 Rust trait object 的标准写法：
- `dyn Tool`：表示"实现了 Tool trait 的某个类型"（具体类型在运行时确定）
- `Box<>`：因为不同工具大小不同，放到堆上统一管理

这样 `tools` 就是一个可以装任何工具的盒子集合。

### 第四步：agent loop 里的 tool_use 处理

S01 的 loop 只处理文本回复，S02 要处理两种情况：

```rust
loop {
    let response = call_api(&client, &api_key, &messages, &tool_defs).await;

    if response.stop_reason.as_deref() == Some("tool_use") {
        // 1. 把 assistant 这轮的 content（可能包含文字+工具调用）存入历史
        messages.push(Message {
            role: "assistant".to_string(),
            content: json!(response.content),
        });

        // 2. 执行所有工具，收集结果
        let mut tool_results = vec![];
        for block in &response.content {
            if let ContentBlock::ToolUse { id, name, input } = block {
                println!("[调用工具] {}", name);
                let result = tools[name].execute(input.clone()).await;
                tool_results.push(json!({
                    "type": "tool_result",
                    "tool_use_id": id,
                    "content": result
                }));
            }
        }

        // 3. 把工具结果作为 user 消息送回去，继续循环
        messages.push(Message {
            role: "user".to_string(),
            content: json!(tool_results),
        });

    } else {
        // stop_reason == "end_turn"，打印文本，结束
        for block in &response.content {
            if let ContentBlock::Text { text } = block {
                println!("\nClaude: {}", text);
            }
        }
        break;
    }
}
```

关键点：**Claude 可以在一轮里同时调用多个工具**，所以要遍历所有 block，把每个 ToolUse 都执行，然后把所有 tool_result 打包成一条 user 消息一起发回去。

---

## 跑起来看效果

输入：`读取 Cargo.toml 的内容然后总结`

```
> 读取 Cargo.toml 的内容然后总结
[调用工具] read_file

Claude: ## Cargo.toml 内容总结

这是一个 Rust 项目的配置文件，主要信息如下：

**项目名称**: learn-claude-code-rust，版本 0.1.0，Rust 2024 edition

**依赖库**（5个）：
- async-trait：在 trait 中支持异步方法
- reqwest：HTTP 客户端，带 json feature
- serde + serde_json：序列化/反序列化
- tokio：异步运行时，full feature
```

agent 自己决定调用 `read_file`，拿到文件内容，然后总结——全程不需要人介入。

---

## 关键洞察：loop 从来没变过

从 S01 到 S02，`agent_loop` 的结构一字没动。变的只是：

| 变化点 | S01 | S02 |
|--------|-----|-----|
| 工具数量 | 0 | 4 |
| 分发方式 | 无 | `HashMap<String, Box<dyn Tool>>` |
| 抽象层 | 无 | `Tool` trait |
| loop 本身 | - | **完全不变** |

以后要加新工具（比如 `fetch_url`、`run_python`）：

1. 新建一个 struct，实现 `Tool` trait
2. 往 HashMap 里 `insert` 一行
3. 完成

**agent loop 不动，工具无限扩展**——这是整个工具系统的设计精髓。

---

## 今天还顺手改了网站

网站 [learncc.cirray.cn](https://learncc.cirray.cn) 本来展示的是 Python 代码，今天一起改成了 Rust。

主要改了三处：

**`extract-content.ts`**：读取目录从 `agents/*.py` 改成 `src/bin/*.rs`，解析 Python class/def 改成 Rust struct/fn，注释符号从 `#` 改成 `//`。

**`source-viewer.tsx`**：代码高亮从 Python 关键字（`def`、`elif`、`None`）换成 Rust 关键字（`fn`、`let`、`impl`、`match`……）。

**`docs/`**：s01、s02 的示例代码全部从 Python 换成 Rust，运行命令从 `python agents/s01.py` 改成 `cargo run --bin s01_agent_loop`。

现在网站上能看到真实的 Rust 代码，而不是翻译自 Python 的版本了。

---

## 今天遇到的 Rust 坑

**坑：`impl Tool for ReadFileTool` 上面漏了 `#[async_trait]`**

报错信息是 `lifetime parameters or bounds on method execute do not match the trait declaration`，和你想的完全不一样——看到 lifetime 报错，第一反应是去查生命周期，但其实是 `async_trait` 宏没加。

规律：只要 trait 定义上有 `#[async_trait]`，每个 `impl` 上也必须加。

---

## 下一步

Day 4：`TodoWriteTool`（先列计划再执行）+ Subagent（派生独立 agent 处理子任务）。

这两个加起来，agent 就从"被动响应"变成"主动规划"了。感兴趣的话，去 [learncc.cirray.cn](https://learncc.cirray.cn) 看 s02 的代码——现在已经是 Rust 版本了。

代码在：[https://github.com/Hamiltonxx/learn-claude-code-rust](https://github.com/Hamiltonxx/learn-claude-code-rust)
