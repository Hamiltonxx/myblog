+++
title = "用 Rust 给静态博客做评论系统"
date = 2026-03-26
description = "不用 Giscus，不用 Artalk，自己用 Axum + SQLite 写一个极简评论后端，配合 Vanilla JS 前端，部署在 ECS 上。"
[taxonomies]
tags = ["rust", "blog"]
+++

## 为什么自己写

最常见的静态博客评论方案是 Giscus——基于 GitHub Discussions，免费无广告。但国内访问 GitHub 不稳定，对读者不友好，直接排除。

然后看了 Artalk，Go 写的单二进制，部署简单。但界面偏"产品化"，头像、徽章、工具栏一堆，跟博客极简风格不搭，CSS 能改颜色但改不了布局结构。

需求其实很简单：匿名评论（填昵称就行）、支持回复、防刷、样式跟博客一致。自己写反而更合适，前后端加起来不到 400 行。

## 后端设计

技术栈：**Axum + SQLite**，用 sqlx 做数据库操作。

接口只有两个：

```
GET  /api/comments?page=/posts/xxx   获取某篇文章的评论
POST /api/comments                   提交评论
```

数据结构：

```sql
CREATE TABLE comments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    page_key    TEXT NOT NULL,      -- 文章路径，如 /posts/xxx
    parent_id   INTEGER,            -- 回复哪条评论，顶级评论为 null
    name        TEXT NOT NULL,
    email       TEXT,               -- 选填，不对外展示
    content     TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
```

处理了三件事：

**XSS 防护**：用 `html-escape` crate 对 name 和 content 做转义，用户输入不会被当作 HTML 执行。

**限流**：用 `OnceLock<Mutex<HashMap>>` 记录每个 IP 的提交时间和次数，60 秒内最多 5 条，超出返回 429。没用任何外部依赖，几十行搞定。

**端口通过环境变量配置**：

```rust
let port = std::env::var("PORT").unwrap_or_else(|_| "3000".to_string());
let addr = format!("127.0.0.1:{port}");
```

部署时在 systemd 里传 `Environment=PORT=9100`，不需要改代码。

## 踩的坑

**sqlx 宏需要 DATABASE_URL**

一开始用 `sqlx::query_as!` 宏，编译报错：

```
error: set `DATABASE_URL` to use query macros online
```

这个宏在编译期验证 SQL，需要能连上数据库。换成普通函数调用就没问题：

```rust
// 改成这样
sqlx::query_as::<_, Comment>("SELECT ...")
    .bind(&params.page)
    .fetch_all(&state.pool)
    .await
```

**Axum 0.8 移除了 `axum::Server`**

`cargo add axum` 装的是 0.8，但网上大多数例子还是 0.7 的写法。0.8 的正确姿势：

```rust
let listener = tokio::net::TcpListener::bind(&addr).await.unwrap();
axum::serve(listener, app.into_make_service_with_connect_info::<SocketAddr>())
    .await
    .unwrap();
```

**服务器 3000 端口已占用**

systemd 起来立刻挂，日志里看到：

```
Os { code: 98, kind: AddrInUse, message: "Address in use" }
```

用 `lsof -i :3000` 查到是个 Node.js 进程占着，改成 9100 就好了。

## 交叉编译

服务器内存小，不想在上面装 Rust 跑 `cargo build`，在本地 Mac 交叉编译成 Linux 二进制直接上传。

```bash
rustup target add x86_64-unknown-linux-musl
brew install FiloSottile/musl-cross/musl-cross
```

在项目里加 `.cargo/config.toml`：

```toml
[target.x86_64-unknown-linux-musl]
linker = "x86_64-linux-musl-gcc"
```

然后：

```bash
cargo build --release --target x86_64-unknown-linux-musl
```

musl 静态链接，产出的二进制没有任何动态库依赖，扔到任何 Linux x86_64 机器上直接跑。编译出来的文件大约 6MB。

## 部署

上传二进制：

```bash
scp target/x86_64-unknown-linux-musl/release/comments-server ubuntu@ECS_IP:~/
sudo mv ~/comments-server /usr/local/bin/
```

创建数据目录（SQLite 文件放这里）：

```bash
mkdir -p /var/lib/comments
```

systemd 服务 `/etc/systemd/system/comments.service`：

```ini
[Unit]
Description=Comments Server
After=network.target

[Service]
Environment=PORT=9100
ExecStart=/usr/local/bin/comments-server
WorkingDirectory=/var/lib/comments
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable comments
sudo systemctl start comments
```

启动后内存占用 676KB，比 Docker 跑任何东西都轻。

## Nginx 反代

在现有的 server 块里加一段：

```nginx
location /api/comments {
    proxy_pass http://127.0.0.1:9100;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
}
```

`X-Real-IP` 这行很重要，后端拿 IP 做限流，如果不传这个，所有请求的 IP 都会是 `127.0.0.1`，限流就失效了。

## 前端

Vanilla JS，不依赖任何框架，一个 `comments.js` 文件。

评论从后端拉下来之后在前端组装成树形结构（顶级评论 + 子回复），用缩进 + 左边框表示层级。时间显示相对时间（"3 分钟前"），hover 显示完整时间。

样式直接用主题的 CSS 变量（`--primary-color`、`--text-pale-color` 等），不额外引入颜色，自动适配亮色/暗色主题。

本地开发时 API 请求本地后端，生产环境走相对路径由 Nginx 转发：

```js
const API = location.hostname === "localhost" || location.hostname === "127.0.0.1"
  ? "http://127.0.0.1:3000/api/comments"
  : "/api/comments";
```

## 集成进 Zola

serene 主题内置了 Giscus 的占位逻辑，模板里有：

```html
{% if show_comment %}
<div class="giscus"></div>
{% include "_giscus_script.html" %}
{% endif %}
```

`_giscus_script.html` 默认是空文件，在博客自己的 `templates/` 目录下创建同名文件覆盖它（Zola 自己的模板优先于主题），里面引入评论组件即可。

开启评论在 `content/posts/_index.md` 的 `[extra]` 里设置：

```toml
comment = true
```

注意是 section 的配置，不是 `zola.toml` 里的全局配置，因为模板读的是 `section.extra.comment`。
+++
