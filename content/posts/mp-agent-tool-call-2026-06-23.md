+++
title = "氢能站Agent系列5 -- 客户端(小程序)Agent Tool Call"
description = "把一堆 contains() 硬匹配替换成 LLM 自主决策调工具，代码更少，识别更准，还能轻松扩展新能力。"
date = 2026-06-23

[taxonomies]
categories = ["项目"]
tags = ["rust", "llm", "tool-call", "axum", "deepseek", "agent"]

[extra]
lang = "zh"
toc = true
+++

小程序 AI 助手（mp-agent）从"关键词匹配"升级成了真正的 Tool Call 驱动。

以前用户问"哪里能加氢？"触发不了，现在可以正确识别并查数据库。

---

## Tool Call 的思路

LLM 本身支持"工具调用"能力：你告诉它有哪些工具可用、每个工具干什么，它自己判断要不要调、调哪个、传什么参数。

整个流程变成两阶段：

```
用户问题
   ↓
[第一次 LLM 调用] 非流式，携带工具定义
   ↓ finish_reason = "tool_calls"
执行工具（查数据库）
   ↓
[第二次 LLM 调用] 流式，携带工具结果
   ↓
流式回答推给用户
```

如果第一次 LLM 判断不需要工具（比如问"氢燃料电池原理"），直接把文字答案返回，跳过数据库，也是流式输出。

---

## 核心类型设计

先把消息结构统一成一个 `OwnedMsg`，能表达所有角色：

```rust
#[derive(Serialize, Clone)]
pub struct OwnedMsg {
    pub role: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub content: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub tool_calls: Option<Vec<ToolCall>>,   // assistant 返回工具调用时用
    #[serde(skip_serializing_if = "Option::is_none")]
    pub tool_call_id: Option<String>,        // tool 角色回传结果时用
}

impl OwnedMsg {
    pub fn system(content: impl Into<String>) -> Self { ... }
    pub fn user(content: impl Into<String>) -> Self { ... }
    pub fn assistant_tool_calls(tool_calls: Vec<ToolCall>) -> Self { ... }
    pub fn tool(id: impl Into<String>, content: impl Into<String>) -> Self { ... }
}
```

工具定义也很简单，就是名字 + 描述 + JSON Schema 参数：

```rust
fn tool_defs() -> Vec<ToolDef> {
    vec![
        ToolDef {
            kind: "function",
            function: FunctionDef {
                name: "find_nearby_stations",
                description: "查询用户附近的加氢站，返回距离、价格、压力等级、空闲枪数",
                parameters: serde_json::json!({
                    "type": "object",
                    "properties": {},
                    "required": []
                }),
            },
        },
        ToolDef {
            kind: "function",
            function: FunctionDef {
                name: "get_consumption_report",
                description: "查询当前登录用户的加氢消费记录汇总",
                parameters: serde_json::json!({
                    "type": "object",
                    "properties": {
                        "period": {
                            "type": "string",
                            "enum": ["this_month", "last_month", "last_7_days"],
                            "description": "查询周期"
                        }
                    },
                    "required": ["period"]
                }),
            },
        },
    ]
}
```

注意 `find_nearby_stations` 的参数是空的——经纬度从 HTTP 请求里拿，不经过 LLM，这样更安全；`get_consumption_report` 的 uid 也是服务端注入，LLM 只负责判断查哪个时间段。

---

## LLM 客户端：两个新方法

`llm.rs` 里新增两个方法，替代原来的 `stream_messages`：

**`chat_with_tools`** — 非流式，检测工具意图：

```rust
pub async fn chat_with_tools(
    &self,
    messages: &[OwnedMsg],
    tools: &[ToolDef],
) -> Result<ToolCallOutcome> {
    // 发请求，temperature=0.0 让判断更确定
    let resp: ToolChatResp = self.client
        .post(self.url())
        .bearer_auth(&self.api_key)
        .json(&ToolChatReq { model: &self.model, messages, tools,
                             tool_choice: "auto", stream: false, temperature: 0.0 })
        .send().await?
        .json().await?;

    let choice = resp.choices.into_iter().next()?;

    if choice.finish_reason == "tool_calls" && !choice.message.tool_calls.is_empty() {
        let calls = choice.message.tool_calls;
        Ok(ToolCallOutcome::ToolCalls {
            assistant_msg: OwnedMsg::assistant_tool_calls(calls.clone()),
            calls,
        })
    } else {
        Ok(ToolCallOutcome::Text(choice.message.content.unwrap_or_default()))
    }
}
```

**`stream_with_history`** — 流式，带完整上下文（含工具结果）生成最终回答：

```rust
pub async fn stream_with_history(
    &self,
    messages: &[OwnedMsg],
) -> Result<BoxStream<'static, Result<String>>> {
    let resp = self.client
        .post(self.url())
        .bearer_auth(&self.api_key)
        .json(&StreamReq { model: &self.model, messages, stream: true, temperature: 0.3 })
        .send().await?;
    Ok(Box::pin(parse_sse(resp.bytes_stream())))
}
```

---

## Chat Handler：两段式流程

```rust
pub async fn chat(State(state): State<AppState>, Json(body): Json<ChatBody>)
    -> Result<Response, AppError>
{
    // 组装消息历史
    let mut msgs = vec![OwnedMsg::system(SYSTEM)];
    for h in &body.history { /* 追加历史 */ }
    msgs.push(OwnedMsg::user(&question));

    // 第一阶段：让 LLM 决策
    let outcome = state.llm.chat_with_tools(&msgs, &tool_defs()).await?;

    match outcome {
        // 不需要工具，直接返回
        ToolCallOutcome::Text(text) => {
            let stream = async_stream::stream! {
                yield sse(&text.replace('\n', "<br>"));
                yield sse("[DONE]");
            };
            Ok(make_sse(stream))
        }

        // 需要工具：执行 → 注入结果 → 流式生成答案
        ToolCallOutcome::ToolCalls { assistant_msg, calls } => {
            msgs.push(assistant_msg);
            for call in &calls {
                let result = dispatch_tool(&state, &call.function.name,
                                          &call.function.arguments,
                                          body.lat, body.lng, &uid).await;
                msgs.push(OwnedMsg::tool(call.id.clone(), result));
            }

            let mut tokens = state.llm.stream_with_history(&msgs).await?;
            let stream = async_stream::stream! {
                while let Some(Ok(t)) = tokens.next().await {
                    if !t.is_empty() { yield sse(&t.replace('\n', "<br>")); }
                }
                yield sse("[DONE]");
            };
            Ok(make_sse(stream))
        }
    }
}
```

关键点：两次 LLM 调用都在进入 SSE stream 之前完成，所以第一次调用失败可以直接返回 HTTP 错误，而不是把错误混进流里。

---

## 工具实现：把数据查出来交给 LLM 组织语言

`find_nearby_stations` 的工作就是查 DB 返回原始文本，LLM 负责把它变成自然语言：

```rust
async fn query_stations(pool: &PgPool) -> Result<Vec<StationRow>> {
    let mut tx = pool.begin().await?;
    // 设置 RLS 会话变量，让当前事务能看到所有企业的站点
    sqlx::query("SELECT set_config('app.enterprise_id', '*', true)")
        .execute(&mut *tx).await?;

    let rows = sqlx::query_as::<_, StationRow>(r#"
        SELECT
            s.station_name AS name,
            CAST(s.latitude  AS float8) AS lat,
            CAST(s.longitude AS float8) AS lng,
            CAST(COALESCE(g.rated_pressure, 0) AS float8) AS pressure,
            CAST(COALESCE(p.price, 0) AS float8) AS price,
            CAST(COALESCE(gc.free,  0) AS int8) AS free_guns,
            CAST(COALESCE(gc.total, 0) AS int8) AS total_guns
        FROM stations s
        LEFT JOIN LATERAL (
            SELECT MAX(rated_pressure) FROM station_guns
            WHERE station_id = s.station_id AND deleted_at IS NULL
        ) g ON true
        LEFT JOIN LATERAL (
            SELECT price FROM prices
            WHERE owner_id = s.station_id AND owner_type = 'station'
              AND deleted_at IS NULL AND status = 1
            ORDER BY effective_date DESC LIMIT 1
        ) p ON true
        LEFT JOIN (
            SELECT station_id,
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE status = 'idle') AS free
            FROM station_guns WHERE deleted_at IS NULL GROUP BY station_id
        ) gc ON gc.station_id = s.station_id
        WHERE s.deleted_at IS NULL
    "#).fetch_all(&mut *tx).await?;

    tx.commit().await?;
    Ok(rows)
}
```

查出来的数据格式化成这样的文本再交给 LLM：

```
找到最近 5 个氢站：
1. 广州越秀区政府配套氢能站 — 0.7km · ¥30.50/kg · 35MPa · 空闲 4/7
2. 广州白云机场配套氢能站 — 5.7km · ¥30.00/kg · 35MPa · 空闲 5/9
...
```

LLM 拿到这个文本之后，会自己做推荐、排版、补充建议——这才是它该干的事。

---

## 实际效果

```
问：附近哪里能加氢
答：以下是您附近 5 个加氢站（按距离排序）：

1. **广州越秀区政府配套氢能站** — 0.7 km，35MPa，¥30.50/kg，空闲 4/7
2. **广州白云机场配套氢能站** — 5.7 km，35MPa，¥30.00/kg，空闲 5/9
...

推荐距离近、价格低的 **越秀站** 或 **白云机场站**。
需要导航或查询消费记录请告诉我 😊
```

---

## 下一步

接下来打算做前端的小程序页面，把这个 SSE 接口接进去，让车主真正用起来。
