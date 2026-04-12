+++
title = "React 把我的 Claude Token 榨干了，所以我换了 HTMX"
description = "用 Claude 辅助开发时，React 项目动辄把 Session Limit 打满——不是因为需求复杂，而是文件太多、上下文太重。换成 HTMX 之后，前端代码量暴跌，开发体验反而更顺。"
date = 2026-04-12

[taxonomies]
categories = ["项目"]
tags = ["htmx", "react", "rust", "axum", "frontend", "claude"]

[extra]
lang = "zh"
toc = true
+++

今天把 Cirray 的聊天前端从 React 彻底迁移到了 HTMX，代码量砍掉大半。其他几个板块暂时不改，做的站点跳转。

---

## 问题的起点：React 把 Token 榨干了

我用 Claude Code 辅助写代码。React 项目有个致命问题：**改一个小功能，Claude 要读十几个文件**——组件、hook、类型定义、路由配置……上下文瞬间撑满，Token Usage Session Limit 直接爆掉。

页面本身并不复杂，就是个聊天界面。但 React 的文件结构就是这样——一个功能散落在好几个地方，读文件的开销省不掉。

除了 token 问题，React 对我这种不以前端为主业的人也不算友好。状态管理、组件通信、构建配置……每次绕进去都要花时间。

---

## 为什么选 HTMX

HTMX 的思路很对我的胃口：**HTML 就是 UI，服务器返回 HTML 片段，浏览器直接塞进去**。不需要 JSON、不需要前端状态管理、不需要构建工具。

对于我这个场景——Rust + Axum 后端，页面交互不复杂——HTMX 几乎是完美的选择：

- 前端逻辑全部内联在一个 Rust 源文件里（HTML 模板 + 少量 JS）
- 服务端直接返回 HTML 片段，`hx-swap="innerHTML"` 塞进去就完事
- Claude 改需求时只需要读一个文件，token 消耗断崖式下降

---

## 迁移过程

原来的 React 前端样式用的是 Tailwind + 自定义配置，迁移时直接换成 Tailwind CDN（Play CDN），样式类名几乎不用改，视觉效果基本一致。

对话列表的加载：

```html
<div id="conv-list"
     hx-get="/talk/conversations"
     hx-trigger="load, convRefresh from:body"
     hx-swap="innerHTML">
  <p class="text-xs text-gray-600 text-center mt-4">加载中…</p>
</div>
```

服务端（Axum）直接返回 HTML 字符串，不需要序列化 JSON、不需要前端再渲染：

```rust
Html(format!(
    r##"<div class="space-y-0.5">
      <p class="text-[10px] text-gray-600 uppercase tracking-widest px-2 mb-2">最近对话</p>
      {}
    </div>"##,
    items
)).into_response()
```

流式聊天（SSE）这块用原生 `fetch` + `ReadableStream` 处理，HTMX 不擅长 SSE，这部分保留了少量 vanilla JS，大约 80 行。

---

## 迁移后的感受

最直观的变化：**Claude 改需求时不再爆 token 了**。整个 /talk 页面的前端代码全在一个 Rust 文件里，Claude 一次性读完，改完，不用来回翻文件。

代码量也少了很多。之前 React 项目光组件就十几个文件，现在 HTML 模板 + JS 加起来不到 500 行，全部内联在后端代码里。

当然也有取舍——复杂交互（比如流式渲染、Markdown 高亮）还是要写 JS，HTMX 不是银弹。但对于这类"内容为主、交互为辅"的页面，它刚刚好。

---

至于合到一个文件里有没有省token这件事，我还没有实际验证。如果没有的话，就还是分文件、分模块吧。  
可以看出，我现在的软件开发方法论也改了。以前写代码基本是，在功能实现的前提下，可读性第一，执行效率第二，文档第三。现在是Token消耗量第一，执行效率第二，可读性第三。 彻底从AI辅助我写代码，变成我辅助AI完成项目。
