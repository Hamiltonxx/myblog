+++
title = "analytics-agent: 把自然语言变成数据库查询"
description = "手里有张数据库，管理层问「上周哪个站点卖得最好」，这篇文章带你看清楚从一句话到流式回答的每一行代码是怎么工作的。"
date = 2026-05-26

[taxonomies]
categories = ["项目"]
tags = ["rust", "axum", "llm", "sse", "text-to-sql", "deepseek", "sqlx"]

[extra]
lang = "zh"
toc = true
+++

今天把氢能 agent 项目里的 `analytics-agent` 完整过了一遍，这个 crate 只做一件事：

> 用户输入一句中文 → LLM 翻译成 SQL → 执行数据库 → LLM 流式解读结果回给用户

整条链路不到 400 行 Rust。下面逐文件、逐行拆解，力求讲清楚「这行在干什么、为什么这么写、换个场景怎么用」。

---

## 整体目录与数据流

```
src/
├── main.rs        ← 程序入口，组装所有零件，启动 HTTP 服务
├── config.rs      ← 从环境变量读配置
├── state.rs       ← 把配置、DB 连接池、LLM 客户端打包成一个全局共享状态
├── error.rs       ← 定义统一错误类型，自动映射 HTTP 状态码
├── schema.rs      ← 自动扫描数据库表结构，生成给 LLM 看的「地图」
├── sql_guard.rs   ← SQL 安全校验：只允许 SELECT，拦截一切写操作
├── llm.rs         ← 封装 DeepSeek API，支持普通调用和流式 SSE
└── chat.rs        ← 核心 handler：接收问题 → 三步走 → 流式推送结果
```

数据流一图胜千言：

```
浏览器 EventSource /chat?q=上周销量
        │
        ▼
   chat handler
        │
        ├─① LLM.complete() ─→ 返回 SQL 字符串
        ├─② sql_guard 校验 → 拦截危险操作
        ├─③ PostgreSQL 执行 → 返回 JSON 数组
        └─④ LLM.stream()  ─→ 逐 token 推送中文解读
                                    │
                                    ▼
                            SSE 事件流回浏览器（打字效果）
```

---

## Cargo.toml — 依赖清单

```toml
axum          # Web 框架，处理 HTTP 请求、SSE 推送
tokio         # 异步运行时，所有 async/await 的底座
sqlx          # 异步 PostgreSQL 驱动，带编译期 SQL 检查
reqwest       # HTTP 客户端，用来调用 DeepSeek API
serde / serde_json  # 序列化/反序列化 JSON
tracing / tracing-subscriber  # 结构化日志
anyhow / thiserror  # 错误处理（两个互补）
futures / async-stream  # 流式数据处理
tower-http    # axum 中间件（CORS、日志）
dotenvy       # 读 .env 文件
bytes / chrono  # 字节缓冲 / 时间处理
```

---

## config.rs — 配置层

```rust
#[derive(Clone, Debug)]
pub struct Config {
    pub deepseek_api_key: String,
    pub deepseek_base_url: String,
    pub deepseek_model: String,
    pub database_url: String,
    pub exposed_schemas: Vec<String>,
    pub max_rows: u32,
    pub bind_addr: String,
}
```

这是一个普通的结构体，每个字段对应一个环境变量。`#[derive(Clone)]` 让它可以被廉价复制——后面会把它塞进 `Arc` 共享给所有请求。

```rust
impl Config {
    pub fn from_env() -> Result<Self> {
        let _ = dotenvy::dotenv();  // 先尝试加载 .env，失败就忽略（生产环境直接用系统环境变量）
        Ok(Self {
            deepseek_api_key: required("DEEPSEEK_API_KEY")?,  // 必填，缺了直接报错退出
            deepseek_base_url: env::var("DEEPSEEK_BASE_URL")
                .unwrap_or_else(|_| "https://api.deepseek.com".into()),  // 有默认值
            exposed_schemas: env::var("EXPOSED_SCHEMAS")
                .unwrap_or_else(|_| "public".into())
                .split(',')            // "public,analytics" → ["public", "analytics"]
                .map(|s| s.trim().to_string())
                .filter(|s| !s.is_empty())
                .collect(),
            max_rows: env::var("MAX_ROWS")
                .ok()
                .and_then(|s| s.parse().ok())  // 解析失败就用默认值 200，不 panic
                .unwrap_or(200),
            // ...
        })
    }
}
```

**设计要点**：必填项用 `required()` 函数，缺少时给出明确报错信息；可选项提供合理默认值，程序永远能启动。

**举一反三**：任何需要读取环境变量的 Rust 服务，建议都做一个 `Config::from_env()` 的集中入口，而不是到处 `env::var()`。好处是：测试时只需 mock 一个结构体，不需要设置真实环境变量。

---

## state.rs — 共享状态

```rust
#[derive(Clone)]
pub struct AppState {
    pub pool: PgPool,           // 数据库连接池（内部已经是 Arc，Clone 是廉价的）
    pub llm: DeepSeek,          // LLM 客户端（内部有 reqwest::Client，同上）
    pub config: Arc<Config>,    // 配置（用 Arc 包裹，避免复制整个 Config）
    pub schema_text: Arc<String>, // 数据库表结构文本，启动时生成一次，所有请求共享
}
```

只有 13 行，却是整个服务的「神经中枢」。axum 会把这个 `AppState` 自动注入到每个请求 handler，任何 handler 都能通过 `State(state): State<AppState>` 拿到它。

**为什么用 Arc？**

`Arc<T>` 是引用计数指针，多个线程可以同时持有同一份数据的只读引用，Clone 只增加引用计数，不复制数据。`Config` 和 `schema_text` 整个生命周期只需要一份，用 `Arc` 比 `Clone` 省内存，比 `&'static` 灵活。

**举一反三**：所有在请求间共享的「只初始化一次」的资源（数据库连接池、HTTP 客户端、配置、模型权重等）都适合放进 `AppState`。

---

## error.rs — 错误处理

```rust
#[derive(Error, Debug)]
pub enum AppError {
    #[error("bad request: {0}")]
    BadRequest(String),

    #[error("sql guard: {0}")]
    SqlGuard(String),

    #[error("db: {0}")]
    Db(#[from] sqlx::Error),   // ← 这行让 sqlx::Error 可以用 ? 自动转成 AppError::Db

    #[error(transparent)]
    Other(#[from] anyhow::Error),  // ← anyhow::Error 同理
}
```

`thiserror` 宏帮我们自动实现了 `std::error::Error` trait，`#[from]` 让 `?` 运算符自动做类型转换。

```rust
impl IntoResponse for AppError {
    fn into_response(self) -> Response {
        let status = match &self {
            AppError::BadRequest(_) | AppError::SqlGuard(_) => StatusCode::BAD_REQUEST,
            _ => StatusCode::INTERNAL_SERVER_ERROR,
        };
        tracing::warn!(error = %self, "request failed");  // 自动打日志
        (status, self.to_string()).into_response()  // HTTP 状态码 + 错误文本
    }
}
```

实现了 `IntoResponse`，axum 就能把 `Result<_, AppError>` 直接当 handler 返回值，错误自动变 HTTP 响应。

**举一反三**：这是 axum 项目的标准错误处理模式。`BadRequest` 对应用户输入问题，`SqlGuard` 对应安全拦截，`Db` 对应数据库错误，`Other` 兜底。业务越复杂，可以往 enum 里加更多变体，但保持每个变体语义清晰。

---

## schema.rs — 数据库「地图」

这个文件只干一件事：把数据库的表结构扫描出来，格式化成 LLM 能读懂的文本。

```rust
pub async fn introspect(pool: &PgPool, schemas: &[String]) -> Result<String> {
    let rows = sqlx::query(
        r#"
        SELECT
            c.table_schema, c.table_name, c.column_name,
            c.data_type, c.is_nullable
        FROM information_schema.columns c
        JOIN information_schema.tables t
          ON t.table_schema = c.table_schema AND t.table_name = c.table_name
        WHERE c.table_schema = ANY($1)
          AND t.table_type = 'BASE TABLE'   -- 只看真实的表，不含视图
        ORDER BY c.table_schema, c.table_name, c.ordinal_position
        "#,
    )
    .bind(schemas)   // 参数化查询，防 SQL 注入
    .fetch_all(pool)
    .await?;
```

`information_schema.columns` 是 PostgreSQL 的内置元数据视图，每个数据库都有，不需要写业务 SQL 就能知道所有表和字段。

输出的文本长这样：

```
- 表 public.stations:
    - id (integer)
    - name (character varying NULL)
    - hydrogen_level (numeric NULL)
    - created_at (timestamp with time zone)
- 表 public.orders:
    - id (integer)
    - station_id (integer NULL)
    - amount (numeric NULL)
    ...
```

这段文本会被原样塞进每次请求的 system prompt，让 LLM 知道「有哪些表、有哪些字段、字段类型是什么」，写出的 SQL 才不会捏造不存在的表名。

**为什么启动时扫描一次而不是每次请求扫？**

表结构几乎不变，扫描有查询开销，而且结果要塞进 LLM 上下文——一次扫描 `Arc<String>` 共享远比每请求查询高效。如果业务需要动态感知 DDL 变更，可以加一个后台定时任务每小时重新扫一次并更新 `AppState.schema_text`。

**举一反三**：这种「启动时 warm-up 一次昂贵操作」的模式在生产系统里很常见。比如加载机器学习模型权重、初始化词典、预热缓存，都适合在 `main()` 里做，而不是在 handler 里懒加载。

---

## sql_guard.rs — 安全护栏

这是整个服务里最重要的安全层。LLM 不可信，它可能被「提示注入」攻击，生成 `DROP TABLE` 之类的危险 SQL。

```rust
const FORBIDDEN: &[&str] = &[
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE",
    "TRUNCATE", "GRANT", "REVOKE", "COPY", "ATTACH", "VACUUM",
    "REINDEX", "CLUSTER", "LOCK", "COMMENT", "SET", "RESET",
    "CALL", "DO", "EXECUTE", "MERGE", "REFRESH",
];
```

黑名单覆盖了所有 DML（数据操纵）、DDL（数据定义）和高危命令。

```rust
pub fn validate(sql: &str) -> Result<String, AppError> {
    let trimmed = sql.trim().trim_end_matches(';').trim();
    
    // 检查 1：不能是空 SQL
    if trimmed.is_empty() {
        return Err(AppError::SqlGuard("empty SQL".into()));
    }
    
    // 检查 2：不允许多条语句（分号分隔的攻击手法）
    if trimmed.contains(';') {
        return Err(AppError::SqlGuard("multiple statements not allowed".into()));
    }

    let upper = trimmed.to_uppercase();
    let first = upper.split_whitespace().next().unwrap_or("");
    
    // 检查 3：必须以 SELECT 或 WITH 开头
    if first != "SELECT" && first != "WITH" {
        return Err(AppError::SqlGuard(format!(
            "only SELECT/WITH allowed, got {first}"
        )));
    }

    // 检查 4：去掉字符串字面量后，扫描关键词黑名单
    let stripped = strip_strings_and_quotes(&upper);
    let words: Vec<&str> = stripped
        .split(|c: char| !c.is_ascii_alphabetic())
        .filter(|s| !s.is_empty())
        .collect();
    for kw in FORBIDDEN {
        if words.contains(kw) {
            return Err(AppError::SqlGuard(format!("forbidden keyword: {kw}")));
        }
    }

    Ok(trimmed.to_string())
}
```

**为什么要 `strip_strings_and_quotes` 再扫关键词？**

考虑这条 SQL：

```sql
SELECT 'DELETE me' AS msg FROM t
```

字符串字面量 `'DELETE me'` 里有 `DELETE`，如果直接大写扫描，会误拦。`strip_strings_and_quotes` 会把所有单引号和双引号内的内容替换成空格，然后再检查剩余 token，就不会误判了。

但是这条应该被拒绝：

```sql
WITH d AS (DELETE FROM t RETURNING *) SELECT * FROM d
```

去掉引号内容后，`DELETE` 作为语句关键词还在，会被正确拦截。

**举一反三**：任何「接受外部文本然后执行」的场景都需要类似的安全层——不管是执行 shell 命令、调用外部 API 还是操作数据库。LLM 生成的内容永远不要无条件信任，必须过校验层。

---

## llm.rs — LLM 客户端

这个模块封装了和 DeepSeek API 的通信，暴露两个公开方法：`complete`（一次性返回）和 `stream`（流式返回）。

### 请求结构体

```rust
#[derive(Serialize)]
struct ChatReq<'a> {
    model: &'a str,
    messages: Vec<Msg<'a>>,
    stream: bool,
    temperature: f32,
}
```

`'a` 是生命周期参数，意思是「这个结构体里的字符串引用，必须至少和结构体本身一样长」。用 `&str` 而不是 `String` 是为了避免堆内存分配，这个结构体只在序列化成 JSON 前存活极短的时间。

### complete — 普通调用（用于生成 SQL）

```rust
pub async fn complete(&self, system: &str, user: &str) -> Result<String> {
    let body = ChatReq {
        model: &self.model,
        messages: vec![
            Msg { role: "system", content: system },  // 给 LLM 定角色和约束
            Msg { role: "user", content: user },      // 用户的实际问题
        ],
        stream: false,       // 不流式，等完整回答
        temperature: 0.0,    // 确定性最高，SQL 生成不需要创意
    };
    let resp = self.client.post(url).bearer_auth(&self.api_key).json(&body).send().await?;
    // 解析响应，取第一个 choice 的 content
    parsed.choices.into_iter().next().map(|c| c.message.content)
}
```

**temperature: 0.0** 是关键细节。生成 SQL 需要精确，越确定性越好。而后面流式解读数据时用的是 `temperature: 0.3`，允许一点「创意」让回答更自然。

### stream — 流式调用（用于解读结果）

流式调用是整个服务「打字效果」的来源。DeepSeek API 用 **SSE（Server-Sent Events）** 协议逐步推送 token，每个事件长这样：

```
data: {"choices":[{"delta":{"content":"上周"}}]}

data: {"choices":[{"delta":{"content":"销量最高的"}}]}

data: [DONE]
```

`parse_sse` 函数负责解析这个格式：

```rust
fn parse_sse<S>(s: S) -> impl Stream<Item = Result<String>> + Send + 'static
where
    S: Stream<Item = reqwest::Result<Bytes>> + Send + 'static,
{
    async_stream::try_stream! {
        let mut buf = String::new();
        futures::pin_mut!(s);
        while let Some(chunk) = s.next().await {
            let chunk = chunk?;
            buf.push_str(std::str::from_utf8(&chunk)?);
            
            // SSE 事件以 "\n\n" 分隔
            while let Some(idx) = buf.find("\n\n") {
                let event: String = buf.drain(..idx + 2).collect();
                for line in event.lines() {
                    let line = line.trim();
                    let Some(data) = line.strip_prefix("data:") else { continue };
                    let data = data.trim();
                    if data == "[DONE]" { return; }  // 流结束标志
                    
                    // 用 JSON pointer 取深层字段 /choices/0/delta/content
                    if let Some(delta) = v.pointer("/choices/0/delta/content").and_then(|x| x.as_str()) {
                        if !delta.is_empty() {
                            yield delta.to_string();  // 产出一个 token
                        }
                    }
                }
            }
        }
    }
}
```

**`async_stream::try_stream!` 是什么？**

这是个宏，让你用同步风格写异步生成器（Rust 目前还没有原生 `yield` 语法的稳定支持）。`yield` 表示「产出一个值给消费者」，`return` 表示「结束这个流」。消费者每次 `stream.next().await` 才会推进执行到下一个 `yield`。

**举一反三**：任何需要「边生产边消费」的场景都可以用这个模式——读大文件逐行处理、实时推送传感器数据、分批从 API 拉数据。关键是生产者和消费者解耦，消费者不需要等所有数据就绪。

---

## chat.rs — 核心 Handler

这是所有逻辑汇聚的地方。整个文件可以用三个步骤概括：

```
用户问题 → [Step 1] NL→SQL → [Step 2] 执行SQL → [Step 3] 流式解读
```

### Handler 签名

```rust
pub async fn chat(
    State(state): State<AppState>,    // axum 自动注入全局状态
    Query(qry): Query<ChatQuery>,     // 从 URL 查询参数解析 ?q=...
) -> Result<Response, AppError> {
```

`ChatQuery` 就是：

```rust
#[derive(Deserialize)]
pub struct ChatQuery {
    pub q: String,
}
```

axum 的 `Query` extractor 会自动把 `?q=上周各站销量` 解析成这个结构体，如果参数缺失会自动返回 400。

### 构建流

```rust
let stream = async_stream::stream! {
    // ---- Step 1: NL → SQL ----
    let system = build_sql_system(&state.schema_text, state.config.max_rows);
    let raw_sql = match state.llm.complete(&system, &question).await {
        Ok(s) => s,
        Err(e) => {
            yield evt("error", &format!("LLM 生成 SQL 失败: {e}"));
            return;  // 出错就终止流
        }
    };
```

`build_sql_system` 把表结构 schema 文本拼进 system prompt，让 LLM 知道有哪些表可用，并明确约束：只允许 SELECT、不要分号、不要 markdown 代码围栏、必须加 LIMIT。

```rust
    let candidate = strip_fences(&raw_sql);  // 去掉 LLM 可能包的 ```sql ... ``` 围栏
    let sql = match sql_guard::validate(&candidate) {
        Ok(s) => s,
        Err(e) => {
            yield evt("error", &format!("SQL 校验未通过: {e}\nLLM 输出: {raw_sql}"));
            return;
        }
    };
    yield evt("sql", &sql);  // 推送一个 "sql" 事件，前端可以展示 SQL
```

**`yield evt("sql", &sql)` 的含义**：这是 SSE 中的一个命名事件，前端可以：

```javascript
source.addEventListener('sql', e => {
    showSqlBlock(e.data);  // 把 SQL 展示给用户看
});
```

### Step 2：执行 SQL

```rust
    let wrapped = format!(
        "SELECT COALESCE(jsonb_agg(t), '[]'::jsonb) \
         FROM (SELECT * FROM ({sql}) sub LIMIT {limit}) t",
        sql = sql,
        limit = state.config.max_rows,
    );
```

这个技巧值得细说。原始 SQL 可能是：

```sql
SELECT station_name, SUM(amount) FROM orders GROUP BY station_name
```

包装后变成：

```sql
SELECT COALESCE(jsonb_agg(t), '[]'::jsonb)
FROM (SELECT * FROM (SELECT station_name, SUM(amount) FROM orders GROUP BY station_name) sub LIMIT 200) t
```

这样做的好处：
1. **无论原始 SQL 返回多少列，统一变成一个 JSON 数组**，`sqlx::query_as::<_, (serde_json::Value,)>` 能直接接收
2. **`COALESCE(..., '[]'::jsonb)** 保证查无结果时返回空数组而不是 NULL
3. **外层加 LIMIT** 防止 LLM 忘加或故意不加导致返回百万行

```rust
    let exec: Result<(serde_json::Value,), sqlx::Error> =
        sqlx::query_as(&wrapped).fetch_one(&state.pool).await;
    let rows = match exec {
        Ok((v,)) => v,
        Err(e) => {
            yield evt("error", &format!("SQL 执行失败: {e}"));
            return;
        }
    };
    let rows_str = serde_json::to_string(&rows).unwrap_or_else(|_| "[]".into());
    yield evt("rows", &rows_str);  // 推送原始数据，前端可以渲染表格
```

### Step 3：流式回答

```rust
    let answer_system = "你是氢能业务数据分析助手。基于给定的 SQL 与查询结果(JSON)，\
                         用简洁中文回答用户。直接引用关键数字；必要时给出对比或趋势观察；\
                         不要重复 SQL。";
    let answer_user = format!(
        "问题：{q}\n\n执行的 SQL：\n{sql}\n\n查询结果(JSON)：\n{rows_str}\n\n请回答：",
        q = question
    );
    let mut tokens = state.llm.stream(answer_system, &answer_user).await?;
    while let Some(tk) = tokens.next().await {
        match tk {
            Ok(text) if !text.is_empty() => yield evt_data(&text),  // 每个 token 立即推送
            Err(e) => { yield evt("error", &format!("流中断: {e}")); return; }
            _ => {}
        }
    }
    yield evt_data("[DONE]");  // 前端用这个信号停止 loading 动画
```

这里把 **SQL 本身也传给了解读 LLM**，这样 LLM 能理解数据来源（比如知道是按周 GROUP BY 的），回答会更准确，也不会编造数据。

### 返回 SSE 响应

```rust
    let sse = Sse::new(Box::pin(stream))
        .keep_alive(KeepAlive::new().interval(Duration::from_secs(15)));
    Ok(sse.into_response())
```

`Box::pin` 把流放到堆上并固定内存地址（异步流内部有自引用，不 pin 就移不了）。`KeepAlive` 每 15 秒发一个空注释行 `: keepalive`，防止浏览器认为连接断了而重连。

---

## main.rs — 把零件组装起来

```rust
#[tokio::main]
async fn main() -> Result<()> {
    // 1. 初始化日志
    tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::try_from_default_env()
            .unwrap_or_else(|_| EnvFilter::new("info")))
        .init();

    // 2. 读配置
    let cfg = Config::from_env()?;

    // 3. 建数据库连接池
    let pool = PgPoolOptions::new()
        .max_connections(8)
        .acquire_timeout(Duration::from_secs(10))
        .after_connect(|conn, _meta| {
            Box::pin(async move {
                // 每个连接建立后，设置语句超时 30s，防止 LLM 生成的慢查询拖垮服务
                sqlx::query("SET statement_timeout = '30s'").execute(&mut *conn).await?;
                Ok(())
            })
        })
        .connect(&cfg.database_url)
        .await?;

    // 4. 扫描 schema（启动时只做一次）
    let schema_text = schema::introspect(&pool, &cfg.exposed_schemas).await?;

    // 5. 创建 LLM 客户端
    let llm = DeepSeek::new(cfg.deepseek_base_url.clone(), cfg.deepseek_api_key.clone(), cfg.deepseek_model.clone());

    // 6. 组装全局状态
    let state = AppState { pool, llm, config: Arc::new(cfg.clone()), schema_text: Arc::new(schema_text) };

    // 7. 配置 CORS（允许前端跨域）
    let cors = CorsLayer::new()
        .allow_methods([Method::GET, Method::POST, Method::OPTIONS])
        .allow_headers(Any)
        .allow_origin(Any);

    // 8. 定义路由
    let app = Router::new()
        .route("/chat", get(chat))
        .route("/health", get(|| async { "ok" }))
        .with_state(state)
        .layer(TraceLayer::new_for_http())  // 自动打印每个请求的日志
        .layer(cors);

    // 9. 启动监听
    let listener = tokio::net::TcpListener::bind(&cfg.bind_addr).await?;
    axum::serve(listener, app).await?;
    Ok(())
}
```

注意 `.after_connect` 这个细节——它在每个连接创建后立刻设置 `statement_timeout`。这是防御性编程：LLM 可能生成全表扫描 SQL，没有超时的话一条慢查询能占用连接池 8 个连接中的一个，积累几个后整个服务就饿死了。

---

## 前端对接

浏览器侧只需要十几行 JS：

```javascript
const source = new EventSource(`/chat?q=${encodeURIComponent(question)}`);

// 拿到 LLM 生成的 SQL（可展示给用户）
source.addEventListener('sql', e => {
    document.getElementById('sql-block').textContent = e.data;
});

// 拿到原始数据（可渲染为表格）
source.addEventListener('rows', e => {
    const rows = JSON.parse(e.data);
    renderTable(rows);
});

// 流式打字效果
source.onmessage = e => {
    if (e.data === '[DONE]') {
        source.close();
        return;
    }
    document.getElementById('answer').textContent += e.data;
};

// 错误处理
source.addEventListener('error', e => {
    console.error('Agent error:', e.data);
    source.close();
});
```

这里用了 SSE 的「命名事件」机制——`sql` 和 `rows` 是用 `event: sql` 字段标注的具名事件，`onmessage` 只接收没有 event 名的默认消息（也就是流式 token）。这样同一条 SSE 连接就能承载多种数据类型，不需要额外的 WebSocket。

---

## 全局视角：这个系统做了哪些权衡

| 设计决策 | 选择 | 理由 |
|---------|------|------|
| NL→SQL 用非流式，解读用流式 | 是 | SQL 要完整拿到再校验，解读要快速给用户反馈 |
| temperature | 0.0 生成 SQL，0.3 解读 | 精确性 vs 流畅性的分场景调整 |
| schema 启动时扫描 | 是 | 省去每次请求的查询开销，schema 基本不变 |
| SQL 安全双保险 | prompt 约束 + 代码校验 | LLM 不可完全信任，代码层是最后防线 |
| 结果包装为 jsonb_agg | 是 | 统一输出格式，同时防大数据量 |
| statement_timeout | 30s | 防慢查询拖垮连接池 |

---

## 下一步可以做什么

- **多轮对话**：把历史问答存入 Redis，让用户能说「再按省份细分一下」
- **Schema 动态更新**：后台定时任务监听 DDL 事件，自动刷新 `schema_text`
- **SQL 审计日志**：把每次生成的 SQL 和执行结果写入 audit 表，方便排查幻觉
- **流式 token 计数**：统计每次请求消耗的 token，用于成本分析

---

整条链路读下来，代码量不多，但每个细节都有充分理由。最大的收获是：**LLM 是不可信的外部输入，必须在语言模型和数据库之间插一个校验层**——这和 Web 开发里永远不要相信用户输入是同一个道理。
