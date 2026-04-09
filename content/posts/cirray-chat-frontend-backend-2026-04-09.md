+++
title = "Cirray Chat 前后端整理"
description = "记录 cirray.cn /chat 功能的完整实现：手机验证码登录、token 长效存储、SSE 流式对话，以及前后端接口设计思路。"
date = 2026-04-09

[taxonomies]
categories = ["项目"]
tags = ["nextjs", "rust", "sse", "authentication", "sqlite", "chat"]

[extra]
lang = "zh"
toc = true
+++

今天把 cirray.cn 的 `/chat` 功能前后端整体实现了一遍，顺手整理成文档。

---

## 整体架构

用户 → `zh.cirray.cn`（Next.js 前端）→ `token.cirray.cn`（Rust/Axum 后端）→ AI 服务

前端是 Next.js 15 App Router，API Routes 充当代理层，解决 CORS 的同时也避免把后端地址暴露给浏览器。后端是 Rust + Axum，SQLite 做用户存储，对外暴露 OpenAI 兼容接口。

下面这张图是完整调用链路（时序图风格）：

<figure>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1100 760" width="100%" style="max-width:1100px;display:block;margin:0 auto;">
  <defs>
    <marker id="m-blue"   markerWidth="9" markerHeight="7" refX="9" refY="3.5" orient="auto"><polygon points="0 0,9 3.5,0 7" fill="#60a5fa"/></marker>
    <marker id="m-green"  markerWidth="9" markerHeight="7" refX="9" refY="3.5" orient="auto"><polygon points="0 0,9 3.5,0 7" fill="#34d399"/></marker>
    <marker id="m-purple" markerWidth="9" markerHeight="7" refX="9" refY="3.5" orient="auto"><polygon points="0 0,9 3.5,0 7" fill="#a855f7"/></marker>
    <marker id="m-orange" markerWidth="9" markerHeight="7" refX="9" refY="3.5" orient="auto"><polygon points="0 0,9 3.5,0 7" fill="#fb923c"/></marker>
    <marker id="m-gray"   markerWidth="9" markerHeight="7" refX="9" refY="3.5" orient="auto"><polygon points="0 0,9 3.5,0 7" fill="#64748b"/></marker>
  </defs>
  <rect width="1100" height="760" fill="#0f172a"/>
  <text x="550" y="30" text-anchor="middle" font-size="17" font-weight="700" fill="white" font-family="-apple-system,'Segoe UI',sans-serif">Cirray Chat — 全链路调用架构</text>
  <rect x="20"  y="48" width="140" height="54" rx="10" fill="#172554" stroke="#3b82f6" stroke-width="1.5"/>
  <text x="90"  y="70"  text-anchor="middle" font-size="19" font-family="sans-serif">💻</text>
  <text x="90"  y="92"  text-anchor="middle" font-size="12" font-weight="600" fill="#93c5fd" font-family="-apple-system,sans-serif">用户浏览器</text>
  <rect x="205" y="48" width="220" height="54" rx="10" fill="#022c22" stroke="#10b981" stroke-width="1.5"/>
  <text x="315" y="66"  text-anchor="middle" font-size="10" fill="#6ee7b7" font-family="monospace">zh.cirray.cn</text>
  <text x="315" y="82"  text-anchor="middle" font-size="13" font-weight="600" fill="white" font-family="-apple-system,sans-serif">Next.js 15 前端</text>
  <text x="315" y="96"  text-anchor="middle" font-size="9"  fill="#34d399" font-family="monospace">App Router · API Routes · SSE</text>
  <rect x="465" y="48" width="310" height="54" rx="10" fill="#2e1065" stroke="#a855f7" stroke-width="1.5"/>
  <text x="620" y="66"  text-anchor="middle" font-size="10" fill="#d8b4fe" font-family="monospace">token.cirray.cn → cal.cirray.cn:3000</text>
  <text x="620" y="82"  text-anchor="middle" font-size="13" font-weight="600" fill="white" font-family="-apple-system,sans-serif">Rust / Axum 后端</text>
  <text x="620" y="96"  text-anchor="middle" font-size="9"  fill="#c084fc" font-family="monospace">SQLite 用户鉴权 · AI Session 代理</text>
  <rect x="820" y="48" width="200" height="54" rx="10" fill="#431407" stroke="#f97316" stroke-width="1.5"/>
  <text x="920" y="70"  text-anchor="middle" font-size="19">🤖</text>
  <text x="920" y="88"  text-anchor="middle" font-size="13" font-weight="600" fill="white" font-family="-apple-system,sans-serif">AI 服务</text>
  <text x="920" y="100" text-anchor="middle" font-size="9"  fill="#fdba74" font-family="monospace">流式响应</text>
  <line x1="90"  y1="102" x2="90"  y2="720" stroke="#1e40af" stroke-width="1.5" stroke-dasharray="5,6" opacity="0.5"/>
  <line x1="315" y1="102" x2="315" y2="720" stroke="#059669" stroke-width="1.5" stroke-dasharray="5,6" opacity="0.5"/>
  <line x1="620" y1="102" x2="620" y2="720" stroke="#7e22ce" stroke-width="1.5" stroke-dasharray="5,6" opacity="0.5"/>
  <line x1="920" y1="102" x2="920" y2="720" stroke="#c2410c" stroke-width="1.5" stroke-dasharray="5,6" opacity="0.5"/>
  <rect x="20" y="116" width="1060" height="20" rx="5" fill="#1e293b"/>
  <text x="30" y="130" font-size="11" font-weight="600" fill="#94a3b8" font-family="-apple-system,sans-serif">🔐  认证（首次登录 · token 无过期）</text>
  <line x1="97" y1="165" x2="306" y2="165" stroke="#34d399" stroke-width="2" marker-end="url(#m-green)"/>
  <text x="200" y="158" text-anchor="middle" font-size="10" fill="#6ee7b7" font-family="-apple-system,sans-serif">输入手机号，点「发送验证码」→ 阿里云短信下发</text>
  <line x1="97" y1="200" x2="306" y2="200" stroke="#34d399" stroke-width="2" marker-end="url(#m-green)"/>
  <text x="200" y="193" text-anchor="middle" font-size="10" fill="#6ee7b7" font-family="-apple-system,sans-serif">输入 6 位验证码，点「登录」</text>
  <line x1="322" y1="238" x2="611" y2="238" stroke="#a855f7" stroke-width="2" marker-end="url(#m-purple)"/>
  <rect x="348" y="219" width="218" height="27" rx="5" fill="#160832" stroke="#6d28d9" stroke-width="0.8"/>
  <text x="457" y="231" text-anchor="middle" font-size="10" fill="#d8b4fe" font-family="monospace">POST /api/auth/verify</text>
  <text x="457" y="243" text-anchor="middle" font-size="9"  fill="#9333ea" font-family="monospace">{ phone, code }</text>
  <rect x="630" y="219" width="268" height="27" rx="5" fill="#160832" stroke="#581c87" stroke-width="0.8"/>
  <text x="764" y="231" text-anchor="middle" font-size="10" fill="#c084fc" font-family="-apple-system,sans-serif">校验验证码 → HMAC 派生密码</text>
  <text x="764" y="243" text-anchor="middle" font-size="9"  fill="#7c3aed" font-family="-apple-system,sans-serif">/auth/login 或 /auth/register → 返回 token</text>
  <line x1="611" y1="278" x2="322" y2="278" stroke="#64748b" stroke-width="1.5" stroke-dasharray="6,3" marker-end="url(#m-gray)"/>
  <text x="467" y="271" text-anchor="middle" font-size="10" fill="#64748b" font-family="monospace">{ token: "3f8a2c…hex 64位，随机，无过期" }</text>
  <rect x="220" y="284" width="190" height="15" rx="3" fill="#0c1a0c" stroke="#166534" stroke-width="0.5"/>
  <text x="315" y="295" text-anchor="middle" font-size="9" fill="#4ade80" font-family="monospace">localStorage["clawtoken_token"] = token</text>
  <rect x="20" y="312" width="1060" height="20" rx="5" fill="#1e293b"/>
  <text x="30" y="326" font-size="11" font-weight="600" fill="#94a3b8" font-family="-apple-system,sans-serif">💬  对话消息流（已登录 · 全程 SSE 流式传输）</text>
  <line x1="97" y1="358" x2="306" y2="358" stroke="#60a5fa" stroke-width="2" marker-end="url(#m-blue)"/>
  <text x="200" y="351" text-anchor="middle" font-size="10" fill="#93c5fd" font-family="-apple-system,sans-serif">输入问题，按 Enter 发送</text>
  <rect x="307" y="364" width="16" height="258" rx="3" fill="#022c22" stroke="#10b981" stroke-width="1" opacity="0.8"/>
  <line x1="323" y1="402" x2="611" y2="402" stroke="#a855f7" stroke-width="2" marker-end="url(#m-purple)"/>
  <rect x="348" y="378" width="238" height="36" rx="5" fill="#160832" stroke="#6d28d9" stroke-width="0.8"/>
  <text x="467" y="391" text-anchor="middle" font-size="10.5" fill="#d8b4fe" font-family="monospace">POST /api/chat</text>
  <text x="467" y="404" text-anchor="middle" font-size="9"   fill="#a855f7"  font-family="monospace">Authorization: Bearer &lt;token&gt;</text>
  <text x="467" y="414" text-anchor="middle" font-size="9"   fill="#7c3aed"  font-family="monospace">{ messages:[…], conversation_id? }</text>
  <rect x="612" y="408" width="16" height="152" rx="3" fill="#2e1065" stroke="#7e22ce" stroke-width="1" opacity="0.8"/>
  <rect x="636" y="424" width="272" height="38" rx="5" fill="#160832" stroke="#6d28d9" stroke-width="0.8"/>
  <text x="772" y="438" text-anchor="middle" font-size="10" fill="#c084fc" font-family="-apple-system,sans-serif">① token → 查 SQLite → 取 project_uuid</text>
  <text x="772" y="452" text-anchor="middle" font-size="9"  fill="#7c3aed" font-family="-apple-system,sans-serif">② 有 conversation_id → 续聊 ｜ 无 → 新建对话</text>
  <line x1="628" y1="490" x2="911" y2="490" stroke="#fb923c" stroke-width="2" marker-end="url(#m-orange)"/>
  <rect x="636" y="468" width="272" height="28" rx="5" fill="#1c0a02" stroke="#c2410c" stroke-width="0.8"/>
  <text x="772" y="481" text-anchor="middle" font-size="9.5" fill="#fdba74" font-family="monospace">转发到 AI 服务（SSE 请求）</text>
  <rect x="912" y="496" width="16" height="72" rx="3" fill="#431407" stroke="#c2410c" stroke-width="1" opacity="0.8"/>
  <line x1="911" y1="534" x2="628" y2="534" stroke="#fb923c" stroke-width="1.5" stroke-dasharray="6,3" marker-end="url(#m-orange)"/>
  <rect x="636" y="515" width="272" height="28" rx="5" fill="#1c0a02" stroke="#c2410c" stroke-width="0.8"/>
  <text x="772" y="527" text-anchor="middle" font-size="9.5" fill="#fdba74" font-family="monospace">SSE 流式响应</text>
  <text x="772" y="538" text-anchor="middle" font-size="9"   fill="#f97316" font-family="monospace">data: { "completion": "回答文字" }</text>
  <line x1="611" y1="580" x2="323" y2="580" stroke="#10b981" stroke-width="1.5" stroke-dasharray="6,3" marker-end="url(#m-green)"/>
  <rect x="348" y="556" width="258" height="36" rx="5" fill="#0c1a10" stroke="#166534" stroke-width="0.8"/>
  <text x="477" y="569" text-anchor="middle" font-size="9.5" fill="#6ee7b7" font-family="monospace">SSE 转换为 OpenAI 兼容格式</text>
  <text x="477" y="581" text-anchor="middle" font-size="9"   fill="#34d399" font-family="monospace">data:{choices:[{delta:{content:"回"}}]}  [DONE]</text>
  <text x="477" y="591" text-anchor="middle" font-size="9"   fill="#16a34a" font-family="monospace">Response Header: X-Conversation-Id: &lt;uuid&gt;</text>
  <line x1="306" y1="630" x2="97" y2="630" stroke="#60a5fa" stroke-width="1.5" stroke-dasharray="6,3" marker-end="url(#m-blue)"/>
  <text x="200" y="623" text-anchor="middle" font-size="10" fill="#93c5fd" font-family="-apple-system,sans-serif">逐字渲染  ·  存 conversation_id，下次续聊用</text>
  <line x1="34"  y1="655" x2="58"  y2="655" stroke="#60a5fa" stroke-width="2" marker-end="url(#m-blue)"/>
  <text x="64"  y="659" font-size="10" fill="#64748b" font-family="-apple-system,sans-serif">请求（实线）</text>
  <line x1="148" y1="655" x2="172" y2="655" stroke="#64748b" stroke-width="1.5" stroke-dasharray="5,3" marker-end="url(#m-gray)"/>
  <text x="178" y="659" font-size="10" fill="#64748b" font-family="-apple-system,sans-serif">响应（虚线）</text>
  <rect x="260" y="648" width="12" height="12" rx="2" fill="#022c22" stroke="#10b981" stroke-width="1"/>
  <text x="278" y="659" font-size="10" fill="#64748b" font-family="-apple-system,sans-serif">组件激活中</text>
  <rect x="20" y="670" width="1060" height="54" rx="8" fill="#1e293b" stroke="#334155" stroke-width="1"/>
  <text x="32" y="688" font-size="11" font-weight="600" fill="#94a3b8" font-family="-apple-system,sans-serif">关键设计说明</text>
  <text x="32" y="706" font-size="10" fill="#64748b" font-family="-apple-system,sans-serif">•  Token：32字节随机 hex，存 SQLite，无过期时间 — localStorage 有值则刷新后无需重新登录</text>
  <text x="32" y="720" font-size="10" fill="#64748b" font-family="-apple-system,sans-serif">•  多轮对话：前端存 conversation_id，后端只发最新一条消息，对话历史由 AI 服务内部维护</text>
</svg>
<figcaption>实线 = 请求，虚线 = 响应，绿色激活框 = 前端处理中，紫色 = 后端处理中</figcaption>
</figure>

---

## 认证模块

### 登录token
没有用JWT.  
现在用户量极小（家庭/团队级），直接用随机 hex token 存 SQLite，简单直接：
- 登录一次，token 永久有效
- 要踢人直接删数据库记录
- 没有任何过期逻辑需要维护

### 登录流程

用手机号+验证码，用户不需要记密码。后端实际上还是 username/password 体系，前端用 HMAC 从手机号派生一个确定性密码，对用户透明。

```
手机号 → 阿里云短信发验证码
用户输入验证码 → 前端调 /api/auth/verify
  → 后端校验验证码（内存 Map，5分钟过期）
  → HMAC-SHA256(phone, VERIFY_SECRET) 派生密码
  → 调后端 /auth/login，失败则先 /auth/register 再 login
  → 返回 token
前端 → localStorage.setItem("clawtoken_token", token)
```

### 前端接口

**发送验证码**

```
POST /api/auth/send-code
Content-Type: application/json

{ "phone": "13800138000" }

→ 200: { "ok": true }
→ 500: { "error": "账户余额不足" }
```

**验证 + 登录/注册**

```
POST /api/auth/verify
Content-Type: application/json

{ "phone": "13800138000", "code": "123456" }

→ 200: { "token": "3f8a2c...64位hex" }
→ 400: { "error": "验证码错误或已过期" }
```

token 取到后存 `localStorage["clawtoken_token"]`，后续所有请求带上：

```
Authorization: Bearer <token>
```

---

## 对话模块

### 前端接口

**发起对话（流式）**

```
POST /api/chat
Content-Type: application/json
Authorization: Bearer <token>

{
  "model": "claude-sonnet-4-6",
  "messages": [
    { "role": "user", "content": "你好" }
  ],
  "stream": true,
  "conversation_id": "057c23fe-..."   // 可选，续聊时传
}
```

**响应：SSE 流**

```
data: {"choices":[{"delta":{"role":"assistant","content":"你"},"finish_reason":null}]}
data: {"choices":[{"delta":{"content":"好"},"finish_reason":null}]}
...
data: [DONE]
```

首次对话响应头里带有：

```
X-Conversation-Id: 057c23fe-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

前端存下这个 id，下次发消息带上，就能续上同一段对话。

### SSE 解析关键代码

```typescript
async function* sseStream(res: Response, abortRef: React.MutableRefObject<boolean>) {
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (!abortRef.current) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      const raw = line.slice(6).trim();
      if (raw === "[DONE]") return;
      const json = JSON.parse(raw);
      const text = json.choices?.[0]?.delta?.content;
      if (text) yield text;
    }
  }
}
```

核心点：`buffer` 处理 TCP 分包，`lines.pop()` 保留未完成的行留到下次拼接。

### 多轮对话设计

后端不存历史消息，历史由 AI 服务那边的 Project/Conversation 机制维护。前端只需要：

1. 首次对话：传完整 `messages` 数组，不传 `conversation_id`
2. 收到响应头里的 `X-Conversation-Id`，存起来
3. 后续对话：只传最新一条 `user` 消息 + `conversation_id`

客户端不用存历史，后端也不用存历史，省事。

---

## 下一步

这套系统稳定跑起来之后，打算先分享给家人和最亲近的朋友用。

一方面，好东西本来就该先给最近的人。顶级 AI 能力现在还不是人手一个，能帮他们养成习惯、真正用起来，比什么都值。另一方面，这些人也是最真实的测试用户——他们不会客气，遇到问题会直接说，比任何 A/B test 都管用。

让家人先跑起来，就是最好的产品测试。
