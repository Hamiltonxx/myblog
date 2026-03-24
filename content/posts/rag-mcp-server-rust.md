+++
title = "用 Rust 构建 RAG + MCP Server：让 CC 读懂你的内部文档"
date = 2026-03-24
[taxonomies]
tags = ["rust", "rag", "mcp", "qdrant", "fastembed", "ai"]
+++

> Python 是 AI 工程的默认语言，但 agentic 系统有一个 Python 解决不了的问题：GIL。当你需要同时跑几百个 agent、每个都在等 embedding 或向量检索的结果，Python 的并发模型就成了瓶颈。
>
> 这篇文章记录我用 Rust 实现的一个完整 RAG + MCP Server——本地文档语义检索，直接接入 Claude Code。不是 demo，是我实际在用的东西。

---

## 背景

MCP（Model Context Protocol）、向量数据库、RAG——这些是 2025 年以来企业 AI 落地最核心的工程方向。用 Python 做这些的教程一抓一大把，但 Rust 几乎没有。

Rust 在这个方向天然有优势：

- **零 GC 停顿**，agent 并发处理请求时延迟稳定
- **单二进制部署**，不需要 Python 环境，边缘设备直接跑
- **编译期类型安全**，tool schema 错误在编译时就能发现

这篇文章记录了我用 Rust 从零搭建的完整链路：

```
本地文档 → fastembed 生成向量 → Qdrant 存储 → MCP Server → Claude Code
```

三个步骤，全部用 Rust 实现。

---

## 技术栈

| 组件 | crate | 用途 |
|------|-------|------|
| Async runtime | `tokio` | 驱动所有异步操作 |
| Embedding | `fastembed` | 本地生成文本向量，无需调外部 API |
| 向量数据库 | `qdrant-client` | 存储和检索向量 |
| MCP Server | `rmcp` | 把搜索能力暴露给 Claude |
| 序列化 | `serde` + `serde_json` | JSON 处理 |
| 目录遍历 | `walkdir` | 递归扫描文档目录 |
| 错误处理 | `anyhow` | 应用层错误统一处理 |

`Cargo.toml` 依赖：

```toml
[dependencies]
tokio = { version = "1.50", features = ["full"] }
fastembed = "5.13"
qdrant-client = "1.17"
rmcp = { version = "1.2", features = ["server", "macros", "transport-io"] }
serde = { version = "1", features = ["derive"] }
serde_json = "1"
schemars = "1"
anyhow = "1"
walkdir = "2"
```

---

## 第一步：文档 Ingest

这一步把本地 Markdown 文档切块、生成 embedding、存入 Qdrant。

```rust
// src/bin/ingest.rs
use anyhow::Result;
use fastembed::{EmbeddingModel, InitOptions, TextEmbedding};
use qdrant_client::qdrant::{
    CreateCollectionBuilder, Distance, PointStruct,
    UpsertPointsBuilder, VectorParamsBuilder,
};
use qdrant_client::Qdrant;
use serde_json::json;
use std::fs;
use walkdir::WalkDir;

const COLLECTION: &str = "cbase";
const VECTOR_SIZE: u64 = 384;

#[tokio::main]
async fn main() -> Result<()> {
    let client = Qdrant::from_url("http://localhost:6334").build()?;

    // 创建 collection（已存在则跳过）
    let exists = client.list_collections().await?
        .collections.iter().any(|c| c.name == COLLECTION);

    if !exists {
        client.create_collection(
            CreateCollectionBuilder::new(COLLECTION)
                .vectors_config(VectorParamsBuilder::new(VECTOR_SIZE, Distance::Cosine)),
        ).await?;
    }

    // 初始化本地 embedding 模型，首次运行自动下载约 80MB
    let model = TextEmbedding::try_new(
        InitOptions::new(EmbeddingModel::AllMiniLML6V2)
            .with_show_download_progress(true),
    )?;

    // 递归扫描文档目录，按空行切块
    let docs_path = std::env::args().nth(1).unwrap_or("docs".to_string());
    let mut texts: Vec<String> = Vec::new();
    let mut paths: Vec<String> = Vec::new();

    for entry in WalkDir::new(&docs_path)
        .into_iter()
        .filter_map(|e| e.ok())
        .filter(|e| {
            e.path().extension()
                .map(|ext| ext == "md" || ext == "txt")
                .unwrap_or(false)
        })
    {
        let content = fs::read_to_string(entry.path())?;
        let path_str = entry.path().to_string_lossy().to_string();

        // 按段落切块，过滤太短的片段
        for chunk in content.split("\n\n").filter(|s| s.trim().len() > 50) {
            texts.push(chunk.trim().to_string());
            paths.push(path_str.clone());
        }
    }

    println!("共 {} 个 chunk，开始生成 embedding...", texts.len());

    // fastembed 在本地运行，batch 处理所有文本
    let embeddings = model.embed(texts.clone(), None)?;

    // 每个 point = 向量 + payload（原文 + 路径）
    let points: Vec<PointStruct> = embeddings
        .into_iter()
        .enumerate()
        .map(|(i, embedding)| {
            PointStruct::new(
                i as u64,
                embedding,
                json!({ "text": texts[i], "path": paths[i] })
                    .try_into().unwrap(),
            )
        })
        .collect();

    client.upsert_points(UpsertPointsBuilder::new(COLLECTION, points)).await?;
    println!("✅ 导入完成，共 {} 个 chunk", texts.len());
    Ok(())
}
```

**几个值得注意的细节：**

`filter_map(|e| e.ok())` 比先 `filter` 再 `map` 更简洁——遇到读取失败的目录条目直接丢弃，不用处理错误。

`texts.clone()` 是必要的：`fastembed` 的 `embed()` 需要所有权，但后面存入 Qdrant 时还需要用 `texts[i]` 取原文，所以只能 clone。更干净的做法是用 `Vec<Chunk>` 结构体统一管理，按需再提取。

`?` 号贯穿始终——任何步骤失败都会立刻返回错误给调用者，配合 `anyhow::Result` 不需要声明具体错误类型。

运行：

```bash
cargo run --bin ingest -- docs
```

---

## 第二步：语义搜索

```rust
// src/bin/search.rs
use anyhow::Result;
use fastembed::{EmbeddingModel, InitOptions, TextEmbedding};
use qdrant_client::qdrant::SearchPointsBuilder;
use qdrant_client::Qdrant;

const COLLECTION: &str = "cbase";

#[tokio::main]
async fn main() -> Result<()> {
    let query = std::env::args().nth(1).unwrap_or("部署环境".to_string());

    let client = Qdrant::from_url("http://localhost:6334").build()?;
    let mut model = TextEmbedding::try_new(
        InitOptions::new(EmbeddingModel::AllMiniLML6V2)
            .with_show_download_progress(false),
    )?;

    // 把查询文本也转成向量
    let embeddings = model.embed(vec![query.clone()], None)?;
    let query_vector = embeddings.into_iter().next().unwrap();

    // 返回最相似的 3 个 chunk
    let results = client.search_points(
        SearchPointsBuilder::new(COLLECTION, query_vector, 3)
            .with_payload(true)
    ).await?;

    for (i, point) in results.result.iter().enumerate() {
        let text: String = point.payload.get("text")
            .and_then(|v| v.as_str())
            .map_or("", |v| v)
            .chars().take(80).collect();
        let path = point.payload.get("path")
            .and_then(|v| v.as_str())
            .map_or("", |v| v);
        println!("{}. [score: {:.3}] {}\n   {}\n", i + 1, point.score, path, text);
    }
    Ok(())
}
```

搜索"测试接口"的实际结果：

```
1. [score: 0.346] docs/自动化测试接口.md
   # 说明 由于部分接口会分散在各个技术文档中，为了统一跑自动化测试流程...

2. [score: 0.312] docs/Python后端开发规范.md
   # 接口设计规范 ## 面向使用者建模 仔细定义"资源"...

3. [score: 0.270] docs/Python后端开发规范.md
   其中，POST/PUT和PATCH的区别在于，全部更新还是局部更新...
```

向量搜索的威力在第 2 条体现出来：搜索词是"测试接口"，但它找到了"接口设计规范"——没有完全匹配的词，但语义相关。关键词搜索做不到这一点。

---

## 第三步：MCP Server

这是整个项目最有趣的部分。把搜索能力包装成 Claude 可以调用的工具，只需要几个宏。

```rust
// src/bin/mcp_server.rs
use anyhow::Result;
use fastembed::{EmbeddingModel, InitOptions, TextEmbedding};
use qdrant_client::qdrant::SearchPointsBuilder;
use qdrant_client::Qdrant;
use rmcp::{
    ServerHandler, ServiceExt,
    handler::server::{router::tool::ToolRouter, wrapper::Parameters},
    tool_handler, tool_router,
};
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use tokio::sync::Mutex;

const COLLECTION: &str = "cbase";

// 定义 tool 的输入参数，schemars 自动生成 JSON Schema 供 Claude 识别
#[derive(Deserialize, Serialize, JsonSchema)]
pub struct SearchRequest {
    /// 搜索关键词或问题
    pub query: String,
}

#[derive(Clone)]
struct DocSearch {
    model: Arc<Mutex<TextEmbedding>>,
    qdrant: Arc<Qdrant>,
    tool_router: ToolRouter<Self>,
}

// #[tool_router] 宏自动生成 tool 注册逻辑
#[tool_router]
impl DocSearch {
    #[rmcp::tool(description = "搜索内部文档，返回最相关的片段")]
    async fn search_docs(&self, Parameters(req): Parameters<SearchRequest>) -> String {
        match self.do_search(&req.query).await {
            Ok(result) => result,
            Err(e) => format!("搜索失败: {}", e),
        }
    }
}

impl DocSearch {
    fn new(model: TextEmbedding, qdrant: Qdrant) -> Self {
        Self {
            model: Arc::new(Mutex::new(model)),
            qdrant: Arc::new(qdrant),
            tool_router: Self::tool_router(),
        }
    }

    async fn do_search(&self, query: &str) -> Result<String> {
        // Mutex 保证多个并发请求不会同时调用 embed()
        let mut model = self.model.lock().await;
        let embeddings = model.embed(vec![query.to_string()], None)?;
        let query_vector = embeddings.into_iter().next().unwrap();
        drop(model); // 立刻释放锁，减少争用

        let results = self.qdrant.search_points(
            SearchPointsBuilder::new(COLLECTION, query_vector, 3)
                .with_payload(true),
        ).await?;

        let mut output = String::new();
        for (i, point) in results.result.iter().enumerate() {
            let text = point.payload.get("text")
                .and_then(|v| v.as_str()).map_or("", |v| v);
            let path = point.payload.get("path")
                .and_then(|v| v.as_str()).map_or("", |v| v);
            output.push_str(&format!(
                "{}. [score: {:.3}] {}\n{}\n\n",
                i + 1, point.score, path, text
            ));
        }
        Ok(output)
    }
}

// #[tool_handler] 宏把 tool_router 接入 MCP 协议的 ServerHandler
#[tool_handler]
impl ServerHandler for DocSearch {}

#[tokio::main]
async fn main() -> Result<()> {
    let model = TextEmbedding::try_new(
        InitOptions::new(EmbeddingModel::AllMiniLML6V2)
            .with_show_download_progress(false),
    )?;
    let qdrant = Qdrant::from_url("http://localhost:6334").build()?;
    let service = DocSearch::new(model, qdrant);

    // stdio transport：Claude Code 通过标准输入输出和 MCP Server 通信
    let transport = rmcp::transport::stdio();
    service.serve(transport).await?;
    Ok(())
}
```

**架构上的关键决策：**

`Arc<Mutex<TextEmbedding>>` 而不是直接持有 `TextEmbedding`——因为 `fastembed` 的 `embed()` 需要 `&mut self`，在 async 环境里多个请求可能并发调用，必须用 Mutex 保护。`Arc` 让 `DocSearch` 可以被 `Clone`（rmcp 要求）。

`drop(model)` 在生成向量后立刻释放锁，而不是等整个函数返回——这样后续的 Qdrant 网络请求期间锁已经释放，其他请求可以并发进来生成 embedding。

编译后接入 Claude Code：

```bash
cargo build --release
claude mcp add cbase ./target/release/mcp_server
```

---

## 效果

在 Claude Code 里直接问：

> 搜索文档：自动化测试接口

Claude 自动调用 `search_docs` tool，返回了文档里的 API 路径、认证方式、接口分类表格——完整的上下文，没有幻觉。

---

## 接下来

这个项目目前只是起点，可以继续扩展的方向：

**换中文 embedding 模型**：`AllMiniLML6V2` 是英文模型，中文文档用 `MultilingualE5Large`（1024 维）效果会好很多，score 分布会更分散，相关性判断更准确。

**改进 chunk 策略**：现在按空行切，粗暴但够用。更好的做法是按 Markdown 标题切，保留完整的段落语境，避免一个列表项被切断。

**加更多 tool**：MCP Server 不只是搜索——可以加"读取完整文件"、"搜索代码库"、"调用内部 REST API"，让 Claude 直接操作你的内部系统。

**Rerank**：向量搜索召回后加一层 rerank（比如用 BM25 或 cross-encoder），精度会有明显提升。

---

最后，我有一个稍微不切实际的想法: 把"Learn-Claude-Code"这个将近4万Star的工程，用Rust实现一遍。不知道我能不能坚持下来...

如果你也在做 Rust + AI 方向，欢迎交流。
