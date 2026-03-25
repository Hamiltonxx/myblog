+++
title = "用 Rust 学 AI Agent——Day 1 & 2：第一次对话 + 网站上线"
description = "两周计划的第一天和第二天：4600 行 Python 变成 200 行 Rust，绕开官方 API 限制让代码真正跑起来，再把网站一路怼上 ECS。"
date = 2026-03-25

[taxonomies]
categories = ["项目"]
tags = ["rust", "ai", "claude", "agent", "learn-agent-rust", "部署", "nginx"]

[extra]
lang = "zh"
toc = true
+++

> 两周计划的第一天，结果把第二天也顺带干完了。
> 比预期顺利——除了两个坑，一个在代码里，一个在服务器上。

---

## Day 1：把 4600 行 Python 变成 200 行 Rust

### 第一步：大扫除

原始仓库是 Python 写的，12 个 session 文件 + `s_full.py`，4600 多行。今天的第一个 commit 是：全部删掉。

`cargo init`，`Cargo.toml` 加上依赖，项目重新从零开始。删完之后仓库清爽多了。

### 第二步：在 `lib.rs` 里把地基打好

每个 session 都要和 Anthropic API 通信，先把核心数据结构定义好放进 `lib.rs`，后续直接 `use`：

```rust
// 对话消息——content 可以是字符串，也可以是 block 数组，用 Value 统一
pub struct Message {
    pub role: String,
    pub content: Value,
}

// content block 枚举，serde 的 tag = "type" 对应 API 返回的 "type" 字段
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ContentBlock {
    Text { text: String },
    ToolUse { id: String, name: String, input: Value },
    ToolResult { tool_use_id: String, content: String },
}
```

这里最值得记一下的是 `ContentBlock`：Anthropic API 返回的 content 是一个数组，每个元素都有 `"type"` 字段，`serde` 的 `tag` 属性正好对上，反序列化直接搞定，不用手动 match 字符串。

### 第三步：S01——agent loop 跑起来

S01 是最基础的 session，目标只有一个：让 Claude **记住上下文**。

没有上下文，每次对话都是全新开始，Claude 不知道你刚才说了什么。有了上下文，它才真正成为一个能连续工作的 agent。

实现很简单——维护一个 `Vec<Message>`，每轮的用户输入和 Claude 回复都追加进去，下次请求把完整历史带上：

```rust
let mut messages: Vec<Message> = vec![];

loop {
    let input = read_user_input();
    messages.push(Message { role: "user".into(), content: json!(input) });

    let response = call_api(&client, &api_key, &messages).await;
    let reply = extract_text(&response);

    println!("Claude: {}", reply);
    messages.push(Message { role: "assistant".into(), content: json!(reply) });
}
```

读输入 → 调 API → 输出 → 存回历史 → 循环。这就是 agent loop 的全部。

### 一个绕不开的现实问题

代码写完，跑起来——沉默。

API 没有响应。原因很简单：国内直连 `api.anthropic.com` 不通。

解法：换一个代理端点，同时注意认证头格式也不一样——官方用 `x-api-key`，代理用标准的 `Authorization: Bearer`：

```rust
// 注释掉的是官方写法
/* .post("https://api.anthropic.com/v1/messages") */
/* .header("x-api-key", api_key) */

// 实际用的
.post("https://api.ofox.ai/anthropic/v1/messages")
.header("Authorization", format!("Bearer {}", api_key))
```

换完之后，第一次对话：

```
> 你好，我叫 Hamilton
Claude: 你好，Hamilton！有什么我可以帮助你的吗？

> 我刚才说我叫什么？
Claude: 你刚才说你叫 Hamilton。
```

上下文记忆正常。S01 完成。

---

## Day 2：把网站怼上 ECS

Day 1 收工的时候，Day 2 的任务是部署项目网站，让别人能通过链接看到进展。环境：阿里云 ECS（Ubuntu），目标域名 `learncc.cirray.cn`。

### 坑一：pm2 启动进程显示 online，curl 一直空

Node.js、Nginx、certbot 都在，只缺 pm2，装好直接启动：

```bash
pm2 start npm --name "learn-site" -- start -- -p 3000
```

`pm2 list` 显示 `online`，内存也有了，但 `curl http://localhost:3000` 一直返回空。

看日志：

```
Error: "next start" does not work with "output: export" configuration.
Use "npx serve@latest out" instead.
```

这个 Next.js 项目配置了 `output: export`，构建产物是 `out/` 目录下的纯静态文件，`next start` 根本不适用，进程实际上一直在崩溃重启——所以 `pm2 list` 显示 online 只是在骗人（pm2 的自动重启让它看起来活着）。

### 坑二：serve 启动慢，以为又崩了

换用 serve 托管静态文件：

```bash
pm2 delete learn-site
pm2 start npx --name "learn-site" -- serve out -p 3000
```

换完之后 curl 还是空。`ss -tlnp | grep 3000` 显示端口在监听，但就是没响应。

差点又去翻日志排查——其实只是 serve 要先下载（`npm warn exec ... serve@14.2.6`），启动比较慢，等几秒就好了。

等了一下，再 curl，HTML 哗哗出来了。

### 收尾：Nginx + HTTPS + DNS

Nginx 反代配置写好：

```nginx
server {
    listen 80;
    server_name learncc.cirray.cn;

    location / {
        proxy_pass http://localhost:3000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

`certbot --nginx` 配 HTTPS，阿里云控制台加 DNS A 记录。

上线后 `https://learncc.cirray.cn` 根路径返回 404，一度以为出问题了。`/en/` 完全正常。查了一下：Next.js 静态导出的根路径重定向是靠 JS 做的，浏览器里正常跳 `/en/`，curl 看到的是 404。不是 bug，是特性。

---

## 小结

今天完成的事：

- 4600 行 Python 换成 200 行 Rust，骨架清晰
- `lib.rs` 公共类型定义好，后续 12 个 session 直接复用
- S01 agent loop 跑通，上下文记忆正常——绕开国内 API 访问限制是关键一步
- 网站上线：`https://learncc.cirray.cn`，HTTPS，能访问

明天 Day 3：`s02_tool_use.rs`，让 agent 从"只会聊天"变成"能执行工具"。
