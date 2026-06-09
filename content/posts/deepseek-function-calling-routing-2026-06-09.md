+++
title = "氢能站Agent系列1 —— Function Calling"
description = "function calling 的核心不是「调函数」，是让模型做路由判断。一步步拆解协议，带你从 JSON 结构到完整流式实现，搭起一套真正能用的智能路由。"
date = 2026-06-09

[taxonomies]
categories = ["学习"]
tags = ["deepseek", "function-calling", "llm", "rust", "openai-api", "sse"]

[extra]
lang = "zh"
toc = true
+++

今天来给氢能管理系统 chatbot 做了一个智能路由：用 DeepSeek 的 function calling 判断"这个问题该不该查业务数据库"，而不是用关键词匹配去猜。

效果很直接——问"现在有多少个氢能站点？"会去真正查数据库然后回答；问"你是谁？"就直接让 DeepSeek 回答，不会傻乎乎地跑一条 SQL。顺手把这个机制从头到尾整理一遍，力求讲清楚。

---

## 先说清楚"function calling"到底是啥

名字有点误导——**function calling 和"调函数"其实没什么关系**。

更准确的描述是：你给模型一份"你有什么能力"的菜单，模型看完用户的问题，告诉你"这题需要用第 3 道菜"——具体怎么做那道菜、做完之后把菜端上来，都是你自己的事，模型不管。

所以整个流程是这样的：

```
你                          DeepSeek
 │                               │
 │── 问题 + 工具菜单 ────────────> │
 │                               │  "这个问题要查数据"
 │ <──── tool_calls ───────────  │
 │                               │
 │  （你自己去查数据库）            │
 │                               │
 │── 查询结果回填 ───────────────> │
 │                               │  "目前系统有 10 个站点"
 │ <──── 最终回答 ──────────────  │
```

如果模型觉得直接回答就够了，就不会有 `tool_calls`，直接给你 `content`。

---

## 协议长什么样——先看 JSON

在写代码之前，先把请求和响应的结构搞清楚，后面就不会懵了。

### 请求：你给模型的"菜单"

比标准的 chat completions 多了两个字段：`tools`（菜单）和 `tool_choice`（让模型自己决定还是强制点某道菜）。

```json
POST /v1/chat/completions

{
  "model": "deepseek-v4-flash",
  "messages": [
    { "role": "user", "content": "现在系统里有多少个氢能站点？" }
  ],
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "query_hydrogen_business_data",
        "description": "查询本系统（氢能业务管理平台）的真实业务数据，例如站点储量、加氢订单等。仅当问题需要查询本系统数据时调用；闲聊不要调用。",
        "parameters": {
          "type": "object",
          "properties": {
            "question": {
              "type": "string",
              "description": "改写后的、清晰描述待查询数据的自然语言问题"
            }
          },
          "required": ["question"]
        }
      }
    }
  ],
  "tool_choice": "auto",
  "temperature": 0.0
}
```

`tool_choice: "auto"` 的意思是"你自己判断要不要调用"，这是我们路由场景想要的。如果写 `"none"` 则禁止调用，强制直接回答；写 `{"type":"function","function":{"name":"xxx"}}` 则强制调用某个具体工具。

---

### 响应 A：模型决定调用工具

`content` 是 `null`，多了一个 `tool_calls` 数组：

```json
{
  "choices": [{
    "message": {
      "role": "assistant",
      "content": null,
      "tool_calls": [{
        "id": "call_abc123",
        "type": "function",
        "function": {
          "name": "query_hydrogen_business_data",
          "arguments": "{\"question\": \"系统中氢能站点的总数\"}"
        }
      }]
    }
  }]
}
```

注意 `arguments` 是一个 **JSON 字符串**，不是对象——需要再 `JSON.parse` 一次才能拿到参数值。这是个容易踩的坑。

---

### 响应 B：模型决定直接回答

普通 chat 响应，没有 `tool_calls`：

```json
{
  "choices": [{
    "message": {
      "role": "assistant",
      "content": "你好！我是 DeepSeek，由中国的 DeepSeek 公司开发的 AI 助手……"
    }
  }]
}
```

---

### 工具执行后的"回填"请求

这是第二次请求，需要把"模型决定调用工具"这件事和"工具执行结果"都拼进对话历史：

```json
{
  "model": "deepseek-v4-flash",
  "messages": [
    { "role": "user", "content": "现在系统里有多少个氢能站点？" },

    // 第一次响应里模型说的"我要调用工具"
    {
      "role": "assistant",
      "content": null,
      "tool_calls": [{ "id": "call_abc123", ... }]
    },

    // 你执行工具后的结果，id 必须和上面对应
    {
      "role": "tool",
      "tool_call_id": "call_abc123",
      "content": "{\"sql\": \"SELECT COUNT(*) FROM stations\", \"rows\": [{\"count\": 10}]}"
    }
  ]
}
```

模型会基于这份完整历史，生成最终的自然语言回答。

---

## 代码实现：从简到繁

### Step 1：最小可运行版（curl 验证思路）

在写 Rust/Python 之前，先用 curl 确认流程是对的：

```bash
curl -s https://api.deepseek.com/v1/chat/completions \
  -H "Authorization: Bearer $DEEPSEEK_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek-v4-flash",
    "messages": [{"role":"user","content":"你好，今天天气怎么样？"}],
    "tools": [{
      "type": "function",
      "function": {
        "name": "get_weather",
        "description": "获取某地的实时天气数据",
        "parameters": {
          "type":"object",
          "properties":{"city":{"type":"string"}},
          "required":["city"]
        }
      }
    }],
    "tool_choice": "auto",
    "temperature": 0
  }'
```

"今天天气怎么样"没有指定城市，模型可能直接回答说"请告诉我城市"，也可能调用工具问北京——看模型的判断。换成"北京今天天气怎么样"，大概率会触发 `tool_calls`。

---

### Step 2：Rust 类型定义——协议类型层（`openai.rs`）

先把协议里的 JSON 结构映射成 Rust 类型。这些类型会贯穿整个实现：

```rust
// openai.rs

use serde::{Deserialize, Serialize};

/// 对话消息，涵盖 user/assistant/tool 三种角色
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ChatMessage {
    pub role: String,
    // assistant 直接回答时有 content；调用工具时 content 为 null
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub content: Option<String>,
    // assistant 角色、调用工具时才有这个字段
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub tool_calls: Option<Vec<ToolCall>>,
    // tool 角色才有，对应 assistant 消息里的 tool_calls[].id
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub tool_call_id: Option<String>,
}

impl ChatMessage {
    /// 构造"工具执行结果"消息，role=tool，tool_call_id 对应上
    pub fn tool_result(tool_call_id: impl Into<String>, content: impl Into<String>) -> Self {
        Self {
            role: "tool".into(),
            content: Some(content.into()),
            tool_calls: None,
            tool_call_id: Some(tool_call_id.into()),
        }
    }
    /// 构造 assistant 的"我决定调用这些工具"消息
    pub fn assistant_with_tool_calls(tool_calls: Vec<ToolCall>) -> Self {
        Self {
            role: "assistant".into(),
            content: None,
            tool_calls: Some(tool_calls),
            tool_call_id: None,
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ToolCall {
    pub id: String,             // 这个 id 要在回填时原样带回去
    #[serde(rename = "type", default = "default_function_type")]
    pub kind: String,           // 目前只有 "function"
    pub function: FunctionCall,
}

fn default_function_type() -> String { "function".into() }

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct FunctionCall {
    pub name: String,
    #[serde(default)]
    pub arguments: String,  // JSON 字符串！不是对象
}

/// 你给模型的"工具菜单条目"
#[derive(Clone, Debug, Serialize)]
pub struct ToolDef {
    #[serde(rename = "type")]
    pub kind: &'static str,       // 固定 "function"
    pub function: FunctionDef,
}

#[derive(Clone, Debug, Serialize)]
pub struct FunctionDef {
    pub name: &'static str,
    pub description: &'static str,
    pub parameters: serde_json::Value,  // JSON Schema 对象
}
```

---

### Step 3：DeepSeek 客户端——两个关键方法（`llm.rs`）

路由判断和最终生成各用一个方法：

```rust
// llm.rs（节选）

impl DeepSeek {
    /// 路由判断：非流式，传入工具定义，返回 assistant 消息。
    /// 返回的消息要么有 content（直接回答），要么有 tool_calls（需要执行工具）。
    pub async fn chat_with_tools(
        &self,
        messages: &[ChatMessage],
        tools: &[ToolDef],
    ) -> Result<ChatMessage> {
        let url = format!("{}/v1/chat/completions", self.base_url.trim_end_matches('/'));

        let body = serde_json::json!({
            "model": &self.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "stream": false,
            "temperature": 0.0   // 路由判断要稳，不需要随机性
        });

        let resp = self.client.post(&url)
            .bearer_auth(&self.api_key)
            .json(&body)
            .send().await?
            .json::<serde_json::Value>().await?;

        // 取出 choices[0].message
        let message: ChatMessage = serde_json::from_value(
            resp["choices"][0]["message"].clone()
        )?;

        Ok(message)
    }

    /// 最终生成：流式，接受完整的多轮 messages（含 tool 角色回填），返回文本增量流。
    /// 工具路由命中后的"生成自然语言回答"走这里；通用问题也走这里。
    pub async fn chat_messages_stream(
        &self,
        messages: &[ChatMessage],
    ) -> Result<BoxStream<'static, Result<String>>> {
        let url = format!("{}/v1/chat/completions", self.base_url.trim_end_matches('/'));

        let body = serde_json::json!({
            "model": &self.model,
            "messages": messages,
            "stream": true,
            "temperature": 0.3   // 生成回答要自然，适当放开随机性
        });

        let resp = self.client.post(&url)
            .bearer_auth(&self.api_key)
            .json(&body)
            .send().await?;

        // 把 SSE 字节流解析成纯文本增量
        Ok(Box::pin(parse_sse(resp.bytes_stream())))
    }
}
```

注意两个方法的 `temperature` 不同——这是分两次请求的额外收益：路由判断和最终生成可以独立调参。

---

### Step 4：核心路由逻辑（`chat.rs`）

这是最关键的部分，串起上面所有的东西：

```rust
// chat.rs

pub async fn chat(
    State(state): State<AppState>,
    Json(req): Json<ChatCompletionRequest>,  // 前端传来的 { messages: [...] }
) -> Result<Response, AppError> {

    // ── 第一步：定义工具菜单 ──────────────────────────────────────────
    let tools = [ToolDef {
        kind: "function",
        function: FunctionDef {
            name: "query_hydrogen_business_data",
            description: "查询本系统（氢能业务管理平台）数据库中的真实业务数据，\
                          例如站点储量、能源现价、加氢订单、调度单、车辆能耗等。\
                          仅当用户问题需要查询本系统业务数据时才调用；\
                          常识性、闲聊、通用知识类问题不要调用。",
            parameters: serde_json::json!({
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "改写后的、清晰描述待查询业务数据的自然语言问题"
                    }
                },
                "required": ["question"],
            }),
        },
    }];

    // ── 第二步：第一次非流式请求，让模型做路由判断 ──────────────────
    let routing = state.llm.chat_with_tools(&req.messages, &tools).await?;

    // 有 tool_calls 且工具名匹配 → 命中，需要查业务数据
    let tool_call = routing
        .tool_calls.as_ref()
        .and_then(|calls| calls.iter().find(|c| c.function.name == "query_hydrogen_business_data"))
        .cloned();

    // ── 第三步：根据路由结果决定走哪条路 ─────────────────────────────
    let stream = async_stream::stream! {
        let final_messages: Vec<ChatMessage> = match &tool_call {

            // ✅ 命中：执行工具，把查询结果回填进对话
            Some(call) => {
                // 从 arguments（JSON 字符串）里解析出 question 参数
                let question = serde_json::from_str::<serde_json::Value>(&call.function.arguments)
                    .ok()
                    .and_then(|v| v["question"].as_str().map(str::to_string))
                    .unwrap_or_else(|| {
                        // 解析失败时兜底：用用户最后说的那句话
                        req.messages.iter().rev()
                            .find(|m| m.role == "user")
                            .and_then(|m| m.content.clone())
                            .unwrap_or_default()
                    });

                // 真正执行工具：NL → SQL → 查库 → JSON
                let tool_content = match run_sql_pipeline(&state, &question).await {
                    Ok((sql, rows_json)) => format!(
                        r#"{{"sql": {}, "rows": {}}}"#,
                        serde_json::to_string(&sql).unwrap_or_default(),
                        rows_json,
                    ),
                    Err(e) => serde_json::json!({ "error": e }).to_string(),
                };

                // 拼接完整对话历史：原始问题 + 助手的"调用决定" + 工具执行结果
                let mut messages = req.messages.clone();
                messages.push(ChatMessage::assistant_with_tool_calls(vec![call.clone()]));
                messages.push(ChatMessage::tool_result(call.id.clone(), tool_content));
                messages
            }

            // ✅ 未命中：原样转发，直接流式生成通用回答
            None => req.messages.clone(),
        };

        // ── 第四步：第二次流式请求，生成最终回答 ────────────────────
        // 两条分支（命中/未命中）在这里汇合，统一流式输出
        let mut tokens = match state.llm.chat_messages_stream(&final_messages).await {
            Ok(s) => s,
            Err(e) => {
                // 生成失败，给前端一个错误提示，然后正常结束流
                yield Ok(Event::default().data(delta_chunk(&format!("生成失败：{e}"))));
                yield Ok(Event::default().data("[DONE]"));
                return;
            }
        };

        while let Some(Ok(text)) = tokens.next().await {
            // delta_chunk() 把文本片段封装成 OpenAI streaming chunk 格式
            // {"choices":[{"delta":{"content":"..."},"index":0}]}
            yield Ok(Event::default().data(delta_chunk(&text)));
        }
        yield Ok(Event::default().data("[DONE]"));
    };

    // 返回 SSE 响应，前端 OpenAIChatProvider 能直接消费
    Ok(Sse::new(Box::pin(stream)).into_response())
}
```

---

## 把这两次请求画成时序图

**命中工具的路径：**

```
前端 ──→ {messages} ──────────────────────────────→ /chat (POST)

/chat ──→ 第一次请求（非流式，带 tools）──────────→ DeepSeek
                                                         │
                                            判断：要查数据！
                                                         │
/chat ←── tool_calls ←───────────────────────────────────┘

/chat ──→ NL → SQL ──────────────────────────────→ DeepSeek
/chat ←── 生成的 SQL ←───────────────────────────────────┘

/chat ──→ 执行 SQL ───────────────────────────────→ PostgreSQL
/chat ←── 查询结果 ←─────────────────────────────────────┘

/chat ──→ 第二次请求（流式，含工具结果）──────────→ DeepSeek
前端  ←── token token ... [DONE] ←───────────────────────┘
```

总共两次 LLM 请求 + 一次数据库查询。

**未命中的路径（纯闲聊）：**

```
前端 ──→ {messages} ──────────────────────────────→ /chat (POST)

/chat ──→ 第一次请求（非流式，带 tools）──────────→ DeepSeek
                                                         │
                                    直接返回 content，无 tool_calls
                                                         │
/chat ──→ 第二次请求（流式）──────────────────────→ DeepSeek
前端  ←── token token ... [DONE] ←───────────────────────┘
```

还是两次 LLM 请求，只是省掉了数据库那一趟。

---

## 几个容易踩的坑

**坑 1：`arguments` 是字符串，不是对象**

```rust
// ❌ 错误：直接把 arguments 当 Value 用
let question = call.function.arguments["question"];

// ✅ 正确：先 parse，再取字段
let args: Value = serde_json::from_str(&call.function.arguments)?;
let question = args["question"].as_str().unwrap_or_default();
```

**坑 2：`tool_call_id` 必须和 `id` 对应**

`assistant` 消息里的 `tool_calls[].id`（比如 `"call_abc123"`）和随后 `tool` 消息里的 `tool_call_id` 必须完全一致。模型靠这个 id 把"调用请求"和"执行结果"对应起来。写错了，模型会困惑，或者干脆报错。

**坑 3：路由判断和流式生成无法合并成一次请求**

这是架构层面的硬约束：

- 流式响应（SSE）是增量到达的，等所有 chunk 拼完才能知道有没有 `tool_calls`
- 在拼完之前，你没法决定"该不该查数据库"
- 所以：**先发一次非流式请求拿路由结果，再发一次流式请求生成回答**——这是 function calling + streaming 的标准做法

**坑 4：description 直接影响路由准确率**

description 写得越精确，模型判断越准。`"查询本系统的业务数据"` 比 `"有用的工具"` 好很多。建议加上几个典型例子，也加上"不适用"的情况（"闲聊、通用知识类问题不要调用"）——这个负向说明非常有效，能防止模型"什么都往工具上靠"。

**坑 5：temperature=0 for 路由判断**

路由判断要稳定可复现，同一个问题问 10 次应该得到同样的路由结果。`temperature=0`（或尽量低）能保证这一点。最终生成回答才需要适当的随机性，让语言更自然。

---

## 为什么不用关键词匹配或意图分类

我最开始也想过用正则：包含"多少个""查询""站点"这些词就走数据库，其他走通用回答。

但这个方案很快就会撑不住：

- "帮我看看最近的补氢调度" → 没有关键词但要查库
- "一共有多少种加氢方式" → 有"多少"但这是常识问题
- "补氢速率计算公式是什么" → 要查专业知识还是查数据库？

维护这套规则会越来越累，而且永远有边界情况。

function calling 把这个判断交给了模型本身，只要 `description` 写得好，它能基于语义理解做出准确判断——这才是真正适合 AI 时代的"路由器"。

---

## 下一步

现在的实现是单轮的——每次请求都是独立的，没有上下文。"那上个月的数据呢？"这类追问会丢失上下文，SQL 生成会失败。

多轮追问的支持需要在 function-calling 路由里引入对话历史管理，后面继续做。
