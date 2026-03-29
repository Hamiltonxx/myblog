+++
title = "用 Rust 学 AI Agent——Day 5：知识按需注入，上下文永不爆炸"
description = "别再把所有 prompt 塞进 system——今天两个机制让 agent 真正「用多少、拿多少」，还能在长对话里自己压缩历史。"
date = 2026-03-29

[taxonomies]
categories = ["项目"]
tags = ["rust", "ai", "claude", "agent", "learn-agent-rust", "context", "skill-loading"]

[extra]
lang = "zh"
toc = true
+++

> Day 4 的 agent 已经能规划、能分身了。
>
> 但还有两个隐患：**知识全堆在 system prompt**，一启动就占满；**对话越来越长**，迟早撞上 context window 上限。
>
> 今天解决这两件事：S05 让 agent 自己决定「什么时候加载什么知识」，S06 让它在长对话里自动压缩历史。

---

## S05：知识不是配置，是工具

### 先理解反模式

很多人搭 agent 的第一反应是：把所有领域知识塞进 system prompt。

```
system = "你是一个助手。以下是你的知识库：\n{3000字的文档}\n{2000字的文档}..."
```

问题显而易见：
1. 每次请求都要发这 5000 字，贵
2. 模型要在海量 system 里找相关信息，准确率下降
3. 知识越来越多，system prompt 没有上限

**S05 的思路完全反过来**：不预加载，让模型自己按需取。

### 核心设计

实现一个 `SkillLoaderTool`，读取 `skills/` 目录下的 `.md` 文件，把内容通过 `tool_result` 注入对话历史：

```rust
struct SkillLoaderTool;

#[async_trait]
impl Tool for SkillLoaderTool {
    fn name(&self) -> &str { "load_skill" }

    fn definition(&self) -> Value {
        json!({
            "name": "load_skill",
            "description": "加载指定技能的知识文档。当你需要某个领域的专业知识时调用此工具。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "skill_name": {
                        "type": "string",
                        "description": "技能名称，对应 skills/ 目录下的子目录名"
                    }
                },
                "required": ["skill_name"]
            }
        })
    }

    async fn execute(&self, input: Value) -> String {
        let skill_name = input["skill_name"].as_str().unwrap_or("");
        let path = format!("skills/{}/SKILL.md", skill_name);

        match std::fs::read_to_string(&path) {
            Ok(content) => content,
            Err(_) => {
                let available = list_skills();
                format!("技能 '{}' 不存在。可用技能: {}", skill_name, available.join(", "))
            }
        }
    }
}
```

`execute` 就是一个文件读取——`std::fs::read_to_string`，两行。

### 流程是这样的

```
用户: "帮我设计一个客服 agent"
  ↓
Claude 判断: 我需要 agent 设计相关知识
  ↓
Claude 调用: load_skill("agent-builder")
  ↓
tool_result: [agent-builder/SKILL.md 的全部内容]
  ↓
Claude 读完，基于知识给出专业回答
```

**关键在这里**：知识进入 `messages[]` 的时机是「模型主动调用工具之后」，而不是启动时写死在 system prompt 里。这条对话里用不到的知识，永远不会出现在 context 里。

### system prompt 只说「有什么」，不说「内容是什么」

```rust
let available = list_skills().join(", ");
let system = format!(
    "你是一个知识丰富的助手。当你需要特定领域的专业知识时，用 load_skill 工具加载对应技能文档。\n可用技能: {}",
    available
);
```

system prompt 只告诉模型「你有哪些技能可以加载」，不塞内容本身。模型自己决定要不要调、调哪个。

### 跑起来的效果

输入："帮我设计一个 agent"：

```
[工具调用] load_skill  {"skill_name": "agent-builder"}
  [加载技能] agent-builder (3421 字节)

Claude: 设计一个 agent 需要考虑三个核心要素：
  1. Capabilities（能做什么）...
```

输入："帮我 review 这段代码"：

```
[工具调用] load_skill  {"skill_name": "code-review"}
  [加载技能] code-review (1876 字节)

Claude: 代码审查建议从以下几个维度...
```

没有任何路由代码，判断完全在模型侧。

---

## S06：messages 太长了，自己压缩

### 先理解问题

agent 的对话历史是追加的——每次工具调用产生两条（`assistant` + `tool_result`），几轮下来 `messages` 轻松到 30、40 条。

大模型的 context window 有限，超了要么报错，要么截断——截断更危险，因为它会悄悄丢掉你以为存在的信息。

### 解法：超过阈值，用模型压缩旧消息

两个常量：

```rust
const COMPACT_THRESHOLD: usize = 20; // 超过这个数触发压缩
const KEEP_RECENT: usize = 10;       // 保留最近 N 条原文
```

每轮 agent loop 开始前调用一次 `maybe_compact`：

```rust
async fn maybe_compact(
    client: &reqwest::Client,
    api_key: &str,
    messages: &mut Vec<Message>,
) {
    if messages.len() < COMPACT_THRESHOLD {
        return;
    }

    // drain 取出前面要压缩的部分
    let to_compress: Vec<Message> = messages.drain(..COMPACT_THRESHOLD - KEEP_RECENT).collect();
    println!("[压缩] 将 {} 条消息压缩为摘要...", to_compress.len());

    let summary = summarize(client, api_key, &to_compress).await;

    // 把摘要插回最前面
    messages.insert(0, Message {
        role: "user".to_string(),
        content: json!(format!("[对话历史摘要]\n{}", summary)),
    });

    println!("[压缩完成] 剩余消息数: {}", messages.len());
}
```

`summarize` 把要压缩的消息拼成文本，发给模型请求摘要：

```rust
async fn summarize(
    client: &reqwest::Client,
    api_key: &str,
    messages: &[Message],
) -> String {
    let text = messages.iter()
        .map(|m| format!("{}: {}", m.role, m.content))
        .collect::<Vec<_>>()
        .join("\n");

    let req = ApiRequest {
        model: "claude-haiku-4-5-20251001".to_string(),
        max_tokens: 1024,
        system: "请将以下对话历史压缩成简洁摘要，保留关键信息、已完成的操作和重要结论。".to_string(),
        messages: vec![Message {
            role: "user".to_string(),
            content: json!(text),
        }],
        tools: None,
    };

    // ... call_api，提取文本返回
}
```

### agent loop 里只加一行

```rust
loop {
    maybe_compact(client, api_key, &mut messages).await;  // ← 只加这一行
    let response = call_api(...).await;
    // 其余完全不变
}
```

agent loop 本身不需要感知压缩发生过——它只看到一个长度可控的 `messages`，继续正常工作。

### Vec 的 drain 是关键

`drain(..N)` 从 Vec 里取出前 N 个元素，返回迭代器，原 Vec 缩短。对比几种方案：

| 方法 | 行为 | 适合场景 |
|------|------|---------|
| `split_at` | 借用，不修改 | 只读 |
| `drain(..N)` | 取出并删除 | 需要消费前 N 个 |
| `truncate(N)` | 保留前 N，删掉后面 | 反向需求 |

这里用 `drain` 最自然——取出要压缩的部分，剩下的自动前移。

---

## 今天的 Rust 收获

| 机制 | 用在哪 | 解决什么问题 |
|------|--------|-------------|
| `std::fs::read_to_string` | SkillLoaderTool | 同步文件读取，两行搞定 |
| `Vec::drain(..N)` | maybe_compact | 取出前 N 条消息并从 Vec 中移除 |
| `Vec::insert(0, ...)` | maybe_compact | 把摘要插回最前面 |

S05 最大的收获不是 Rust 语法，而是设计思路：**知识是工具，不是配置**。把所有知识扔进 system prompt 是懒惰的做法，让模型自己决定要什么，才是正确的抽象。

---

## 下一步

Day 6-7 是缓冲期：修 bug、补注释、`git pull` 更新网站。

然后 Day 8 开始任务系统（S07）——`Task` struct 带依赖关系，要做图的拓扑排序，终于到 Rust 更有趣的部分了。

代码在：[https://github.com/Hamiltonxx/learn-claude-code-rust](https://github.com/Hamiltonxx/learn-claude-code-rust)
