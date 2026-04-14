+++
title = "两周计划：深入理解 axum + htmx + SSE，Cirray Chat 的全栈路线"
description = "Cirray Chat 已经从 React 切换到 HTMX。这个两周计划以现有代码为锚点，系统学习 axum 路由/状态/中间件、htmx 核心指令、SSE 流式推送，同时补全所有你在项目里用到但还没完全搞懂的细节。"
date = 2026-04-14

[taxonomies]
categories = ["项目"]
tags = ["rust", "axum", "htmx", "sse", "学习计划", "cirray"]

[extra]
lang = "zh"
toc = true
+++

> React 放弃了，HTMX 进来了。Token越烧越多，代码越砌越多，Bug始终解决不了。这时就会恨不得亲自操刀，来个精准手术。
> 这个计划用两周时间，以 Cirray Chat 的 `src/main.rs` 为主线，把里面每一个你"copy-paste 能跑但说不清楚"的模式讲透。

---

## 为什么做这件事

Cirray Chat 切换到 HTMX 之后，整个前后端的交互方式变了：

- **后端**：axum handler 直接返回 HTML 片段，而不是 JSON
- **前端**：htmx 负责把局部 HTML 替换到页面里，不再需要虚拟 DOM
- **流式输出**：SSE（Server-Sent Events）把 Claude 的 token 一个个推到浏览器

这三件事在现有代码里都已经实现了，但"能跑"和"真的懂"之间还有距离。两周之后，你应该能：

1. 独立解释 `main.rs` 里每一个 axum 模式的工作原理
2. 不查文档写出 htmx 的核心交互
3. 理解 SSE 在 axum 里从 stream 到浏览器的完整链路
4. 知道什么时候用 htmx、什么时候还是要用 JS

---

## 项目现状速览

当前 `cirrayclaude/src/main.rs`（约 2900 行）已经包含：

| 模块 | 代码位置 | 用到的核心概念 |
|------|----------|---------------|
| AppState 共享状态 | `struct AppState` | `Arc<AppState>`、`State` extractor |
| Cookie 鉴权 | `cookie_auth` | `HeaderMap`、手写 cookie 解析 |
| HTMX 登录流程 | `talk_send_code` / `talk_verify` | `hx-post`、`hx-target`、`hx-swap` |
| SSE 流式聊天 | `talk_stream` | `Sse<S>`、`KeepAlive`、`tokio::spawn` |
| HTML 模板 | `chat_html` / `login_html` | 服务端 HTML 生成、内联 JS |
| HX-Redirect | `redirect_resp` | HTMX 响应头控制导航 |
| GeoIP 缓存 | `is_china_ip` | `Arc<RwLock<HashMap>>` |

---

## 总体策略

```
第 1 周：读懂现有代码，补基础（axum 核心 + htmx 核心 + SSE 机制）
         每天对照 main.rs 的一个模块，先读后写小实验

第 2 周：动手改进 Cirray Chat，把学到的东西用起来
         每天一个功能改进，做完能直接 git push 到线上
```

**每天的交付物**：一个能运行的小实验 **或** 一个对 Cirray Chat 的真实改动。

---

## 第 1 周

### Day 1（周一）—— axum 骨架：Router / State / Handler

**目标：搞清楚 `main.rs` 第 184 行那个巨大的 `Router::new()` 是怎么工作的**

上午：读代码

- [ ] 读 `main()` 函数（第 110-220 行），画出路由表
- [ ] 理解 `Arc<AppState>` 为什么要用 Arc：State 会被所有 handler clone，必须共享所有权
- [ ] 理解为什么 `AppState` 需要 `#[derive(Clone)]`：axum 每次请求会 clone state

下午：写实验

```rust
// 新建 examples/day1_router.rs
// 复现 main.rs 的最小版本：3 个路由 + AppState + ping handler
// 重点：不用查文档，手写 State extractor
```

- [ ] 运行成功，curl 测试 3 个端点
- [ ] 理解 `extract::State<Arc<AppState>>` 为什么要写这么长

**axum 概念：** `Router::new().route()` 链式调用、`State` extractor、handler 签名

---

### Day 2（周二）—— axum extractor：从请求里拿数据

**目标：搞清楚 handler 参数怎么从 HTTP 请求变成 Rust 类型**

上午：读代码

- [ ] 读 `register`（第 232 行）：`Form<AuthRequest>` — 表单解析
- [ ] 读 `talk_stream`（第 1700 行）：`Json<TalkStreamReq>` — JSON body
- [ ] 读 `talk_load_msgs`（第 1618 行）：`Path(conv_id): Path<String>` — URL 参数
- [ ] 读 `talk_list_convs`（第 1576 行）：`headers: HeaderMap` — 请求头

下午：写实验

```rust
// examples/day2_extractors.rs
// 一个 handler 同时用 State + Path + Json + HeaderMap
// 返回：把解析到的数据 echo 回去
```

- [ ] 理解 extractor 的顺序规则：`State` 必须放第一个
- [ ] 理解为什么 `Json<T>` 要求 T 实现 `Deserialize`

**axum 概念：** extractor 顺序、`Form` vs `Json` vs `Path`、`TypedHeader`

---

### Day 3（周三）—— axum 响应：返回各种类型

**目标：搞清楚 handler 怎么返回 HTML、重定向、状态码、自定义 header**

上午：读代码

- [ ] 读 `talk_page`（第 1359 行）：`Html(...).into_response()`
- [ ] 读 `redirect_resp`（第 1309 行）：手动设置 `HX-Redirect` header
- [ ] 读 `talk_logout`（第 1565 行）：同时设置 header + cookie 清除
- [ ] 读 `talk_delete_conv`（第 1669 行）：`StatusCode::NO_CONTENT.into_response()`

下午：写实验

```rust
// examples/day3_responses.rs
// 实现 4 种响应：
// GET /html  → Html("<h1>hello</h1>")
// GET /json  → Json(serde_json::json!({"ok": true}))
// GET /redirect → 302 + Location header
// GET /custom → 200 + X-Custom-Header: foo
```

- [ ] 理解 `IntoResponse` trait：任何实现了它的类型都能从 handler 返回
- [ ] 理解 `Response` 类型：最底层的返回类型，可以随意设置 header

**axum 概念：** `Html`、`Json`、`StatusCode`、`IntoResponse`、手动构建 `Response`

---

### Day 4（周四）—— SSE：从 stream 到浏览器

**目标：完全搞清楚 `talk_stream`（第 1700 行）的工作原理**

这是整个项目最复杂的部分，也是最值得深挖的地方。

上午：读代码，逐行注释

```rust
// 跟着这个顺序读 talk_stream：
// 1. cookie_auth → 鉴权
// 2. claude_request → 获取上游 SSE 响应（返回 reqwest::Response）
// 3. res.bytes_stream() → 把响应体变成字节流
// 4. sse_lines() → 把字节流切割成行（见第 1229 行）
// 5. .map(|line| { ... }) → 把每一行解析成 SSE Event
// 6. .flat_map(...) → 一行可能产生多个 Event，展开
// 7. Sse::new(sse).keep_alive(...) → 包装成 SSE 响应
```

- [ ] 理解 `sse_lines`（第 1229 行）：为什么需要手动分行？
- [ ] 理解 `tokio::spawn` 在 `is_stop` 时保存对话：为什么不能在 stream 里直接 await？

下午：写最小 SSE 实验

```rust
// examples/day4_sse.rs
// GET /count → 每 500ms 推一个数字，推 10 个后结束
// 用 async_stream::stream! 宏生成流
// 浏览器打开 /count，用 curl --no-buffer 验证
```

- [ ] 用浏览器 EventSource API 接收，看到数字一个个出现
- [ ] 理解为什么 SSE 比 WebSocket 简单：单向推送、HTTP 协议、自动重连

**核心概念：** `Stream` trait、`Sse<S>`、`Event`、`KeepAlive`、`tokio::spawn` 的使用场景

---

### Day 5（周五）—— htmx：核心三件套

**目标：不查文档，默写出 `main.rs` 里用到的所有 htmx 属性**

上午：读 HTML 模板里的 htmx 用法

- [ ] `phone_form_html`（第 1805 行）：
  - `hx-post="/talk/send-code"` — 触发请求
  - `hx-target="#auth-wrap"` — 把响应放到哪
  - `hx-swap="outerHTML"` — 替换目标本身（不是内部）
- [ ] `code_form_html`（第 1824 行）：
  - `hx-target="#err"` + `hx-swap="innerHTML"` — 只更新错误提示区域
  - `htmx.ajax()` — 在 JS 里手动触发 htmx 请求
- [ ] `chat_html` 里的流式消息处理（搜索 `hx-` 关键字）

下午：写 htmx 实验页面

```html
<!-- examples/htmx_demo.html（配合一个 axum server） -->
<!-- 实现：搜索框 → 实时搜索结果（每次按键触发，结果替换到 #results） -->
<!-- 用到：hx-get、hx-trigger="keyup delay:300ms"、hx-target、hx-swap -->
```

- [ ] 理解 `hx-swap` 的 8 种模式：innerHTML / outerHTML / beforebegin / afterend / 等
- [ ] 理解 `hx-trigger` 修饰符：`delay:`、`throttle:`、`changed`

**htmx 概念：** 请求属性三件套、swap 策略、trigger 修饰符

---

### Day 6-7（周末）—— 缓冲 + 补全

**这两天的任务**：

- [ ] 重新读一遍 `main.rs` 第 1256 行到结尾，把前 5 天没搞懂的地方标出来
- [ ] 重点补：`Arc<Mutex<T>>` vs `Arc<RwLock<T>>` 的区别（项目里两种都有）
- [ ] 重点补：`he()` 函数（第 1298 行）—— 为什么每个插入 HTML 的字符串都要过一遍它？
- [ ] 重点补：`HX-Redirect` vs 普通 302 重定向的区别——htmx 为什么需要这个？
- [ ] 写一段总结，回答：「Cirray Chat 的前端交互流程是什么？从用户点发送到消息出现在屏幕上经过了哪些步骤？」

**不要跳过周末。** 学编程最大的陷阱是"看懂了"但没有内化。写下来，才算真的懂。

---

## 第 2 周

第 2 周从"读懂别人的代码"切换到"自己动手改代码"。每天一个改进，做完直接上线。

### Day 8（周一）—— 把 HTML 模板从 main.rs 里拆出去

**目标：`main.rs` 里的 HTML 字符串太长，用 `include_str!` 宏分离到独立文件**

**现状问题：** `chat_html`（第 1974 行）和 `login_html`（第 1861 行）是几百行的内联字符串，改起来非常难受，IDE 没有语法高亮。

**方案：**

```
src/
  templates/
    login.html     ← 从 login_html() 里提取
    chat.html      ← 从 chat_html() 里提取
  main.rs          ← 用 include_str! + format!() 替换
```

- [ ] 提取 `login.html`，在 Rust 里用 `include_str!("templates/login.html")` 加载
- [ ] 动态部分（masked phone、is_cn 的 CDN 地址）用 `{placeholder}` + `str.replace()` 插入
- [ ] `cargo build` 通过，`/talk` 页面功能不变
- [ ] git push

**学到什么：** `include_str!` 宏（编译时嵌入）、Rust 字符串替换策略

---

### Day 9（周二）—— 改进错误处理：用 `?` 替代 unwrap

**目标：消灭 `main.rs` 里的 `.unwrap()` 和 `.unwrap_or_default()`**

**现状问题：** 搜索 `unwrap` 在整个文件里有很多，遇到意外数据可能 panic。

- [ ] 定义统一的错误类型或用 `anyhow::Error`（Cargo.toml 里已有 anyhow）
- [ ] 给需要返回 HTTP 错误的函数改成 `Result<Response, AppError>`
- [ ] 实现 `IntoResponse for AppError`，错误自动变成 500 响应
- [ ] 重点改 `talk_stream` 和 `talk_verify` 这两个最复杂的 handler
- [ ] git push

**学到什么：** axum 的错误处理模式、`IntoResponse` for 自定义错误、`?` 在 async fn 里的用法

---

### Day 10（周三）—— SSE 改进：加上 `conv_id` 事件

**目标：让前端在 SSE 流开始时就能拿到新对话的 ID**

**现状问题：** `talk_stream`（第 1795 行）在 SSE 响应头里放了 `X-Conversation-Id`，但前端在流结束前拿不到这个 ID（htmx 不会主动读响应头里的自定义字段）。

**方案：** 在 SSE 流的**第一个 event** 里发送 `conv_id`：

```
event: meta
data: {"conv_id": "xxxx-xxxx"}

event: delta
data: {"choices": [{"delta": {"content": "你好"}}]}

...
data: [DONE]
```

- [ ] 修改 `talk_stream`：在第一个真实 delta 之前 push 一个 `event: meta` event
- [ ] 前端 JS：监听 `meta` event，拿到 `conv_id` 更新当前状态
- [ ] 测试：新对话第一条消息，conv_id 能正确更新
- [ ] git push

**学到什么：** SSE 的 `event:` 字段（named events）、axum `Event::default().event("meta").data(...)`

---

### Day 11（周四）—— htmx 改进：对话列表自动刷新

**目标：消息发送完成后，左侧对话列表自动更新**

**现状问题：** 发完消息后，如果是新对话，左侧列表不会自动出现新条目，需要手动刷新。

**方案：** 用 htmx 的 `HX-Trigger` 响应头 + `hx-trigger="convUpdated from:body"` 监听事件：

```
// SSE 结束时，服务端发送：
HX-Trigger: convUpdated

// 对话列表容器上：
<div hx-get="/talk/conversations"
     hx-trigger="convUpdated from:body"
     hx-swap="innerHTML">
```

- [ ] 了解 `HX-Trigger` 响应头：服务端触发前端事件的标准机制
- [ ] 在 `talk_stream` 的 `[DONE]` event 里附带触发信号
- [ ] 前端列表容器监听该事件，自动重新加载
- [ ] git push

**学到什么：** `HX-Trigger` 响应头、htmx 自定义事件系统、服务端驱动前端

---

### Day 12（周五）—— 中间件：请求日志 + 耗时统计

**目标：每个请求打印 `[GET /talk] 200 42ms` 这样的日志**

**现状：** tower-http 的 `trace` feature 已经在 Cargo.toml 里了，但没有充分利用。

- [ ] 配置 `tower_http::trace::TraceLayer`，加到 Router 上
- [ ] 配置 tracing-subscriber 的日志格式（目前可能是默认格式）
- [ ] 确认每个请求都有结构化日志输出
- [ ] 加一个自定义中间件：请求 IP 打印（从 `X-Real-IP` 读）
- [ ] git push

**学到什么：** tower middleware 层、`TraceLayer` 配置、tracing span

---

### Day 13（周六）—— 深挖：Arc/Mutex/RwLock 用法整理

**目标：搞清楚 `main.rs` 里 3 种并发原语的选择逻辑**

项目里同时用了三种：

```rust
// Arc<Mutex<HashMap>>  —— sms_codes（短信验证码）
sms_codes: Arc<Mutex<HashMap<String, (String, u64)>>>,

// Arc<RwLock<HashMap>> —— geo_cache（GeoIP 缓存）
geo_cache: Arc<RwLock<HashMap<String, bool>>>,

// Arc<Mutex<String>>   —— talk_stream 里的 acc（累积文本）
let acc = Arc::new(Mutex::new(String::new()));
```

- [ ] 写一份对比文档（注释形式）：三种用法的区别和选择依据
- [ ] 回答：为什么 geo_cache 用 `RwLock` 而 sms_codes 用 `Mutex`？
- [ ] 实验：把 geo_cache 改成 `Mutex`，性能有什么差异？（理论推导即可）
- [ ] 思考：在 tokio 环境里，应该用 `std::sync::Mutex` 还是 `tokio::sync::Mutex`？什么时候各自合适？

**学到什么：** 读多写少用 `RwLock`、tokio Mutex vs std Mutex 的阻塞语义

---

### Day 14（周日）—— 整理 + 文档 + 下一步

**目标：为未来的自己留下地图**

上午：整理
- [ ] 给 `main.rs` 里没有注释的核心函数补上中文注释（重点：`sse_lines`、`talk_stream`、`claude_request`）
- [ ] 在 README 或 NOTES.md 里写一份「架构速查」：路由表、数据流图

下午：规划下一步

**下一个值得做的改进：**

| 方向 | 具体改进 | 难度 |
|------|----------|------|
| 性能 | 把 HTML 模板用 minijinja/askama 管理 | ★★☆ |
| 功能 | 支持多模型选择（下拉菜单，htmx swap） | ★★☆ |
| 可维护 | 把 main.rs 按模块拆分（auth.rs / chat.rs / templates/） | ★★☆ |
| 安全 | Cookie 加签名验证（防篡改） | ★★★ |
| 体验 | SSE 中断后自动重试（EventSource reconnect） | ★★☆ |

- [ ] 选一个，记录到项目 TODO

---

## 风险预案

| 如果…… | 怎么办 |
|--------|--------|
| Day 4 SSE 卡太久理解不了 | 先跳过，继续看 htmx，周末再回来 |
| Day 8-12 改动破坏了线上功能 | 先在本地测试，用 `cargo test` + curl 验证再 push |
| 某天状态不好，什么都不想做 | 只做"读代码"部分，不写实验，也算完成 |
| 某个改进比预期复杂 | 缩小范围，做最小可用版本，加 TODO 注释 |

---

## 每日节奏

```
09:00 - 09:30  读当天对应的 main.rs 代码区域，画流程图或写伪代码
09:30 - 11:30  写实验代码 / 改进代码
11:30 - 12:00  cargo check + 测试
13:00 - 14:30  调试卡住的地方（第 2 周：git push + 线上验证）
14:30 - 15:30  写当天的学习笔记（一段话够了）
15:30 - 16:00  预习明天的内容
```

---

## 两个判断标准

**一周结束时，问自己这个问题：**
> "如果有人问我 `talk_stream` 里 SSE 是怎么工作的，我能不打开文件，把流程讲清楚吗？"

**两周结束时，问自己这个问题：**
> "如果要从零实现一个类似的 HTMX 聊天页面，我知道从哪里开始，怎么一步步做吗？"

能回答"是"，这两周就值了。

---

## 最后

从 React 切到 HTMX，最大的转变不是技术，是思维：
**页面交互的状态从客户端转移到了服务端。**

服务端说什么，浏览器就展示什么。没有 Redux，没有 useState，没有 hydration。
这个模型更简单，但也要求你更清楚地理解 HTTP 和 HTML 本身。

Cirray Chat 的代码已经是这个模型的一个真实案例。
两周之后，这份代码应该是你的，不是你 copy 进来的。
