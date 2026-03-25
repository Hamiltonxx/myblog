+++
title = "两周计划：用 Rust 实现 learn-agent，从零到发布"
description = "一个关于想法、勇气和坚持的两周计划——用 Rust 重写 learn-claude-code 的全部 12 个 session，同时深入理解 AI Agent 的核心原理。"
date = 2026-03-25

[taxonomies]
categories = ["项目"]
tags = ["rust", "ai", "claude", "agent", "学习计划"]

[extra]
lang = "zh"
toc = true
+++

> 有时候，最好的学习方式不是跟着教程走，而是选一个你有点怕的目标，然后逼自己完成它。
> 这个计划就是这样来的：用 Rust 重写 [learn-claude-code](https://github.com/shareAI-lab/learn-claude-code) 的全部 12 个 session，
> 边做边深入理解 AI Agent 的工作原理，同时把 Rust 编码能力提升到一个新的台阶。

---

## 为什么做这件事

这个计划背后有三个层次的动力：

**第一层：真正理解 AI Agent。** 光看文档或跑别人的代码，理解是浅的。把每一个机制——agent loop、tool dispatch、subagent、context compression、multi-agent 协作——亲手用 Rust 实现一遍，才会真正明白它们是怎么工作的。

**第二层：把 Rust 用起来。** Rust 学了忘、忘了学，根本原因是没有足够真实的项目驱动。这个计划每个 session 都对应一个具体的 Rust 能力点，做完之后 Rust 就不再是"我学过但没用过"的语言了。

**第三层：需要一点勇气。** 两周完成 12 个 session + 网站部署 + 对外发布，这个目标有点大。但正是因为有点大，才值得去做。畏手畏脚只能做容易的事；敢于设定高目标，才能真正成长。

---

## 总体策略

```
第 1 周：基础设施 + 核心 sessions（s01-s06）
         目标：GitHub 仓库能看，网站能访问，6 个 session 能跑

第 2 周：进阶 sessions（s07-s12）+ 网站改造 + 发布
         目标：12 个 session 完成，网站展示 Rust 代码，去原仓库提 issue
```

每天的交付物都是**一个 git commit**，推上去就能看到进展。
如果某天提前做完，可以预习下一天的内容，但不要跳天。

---

## 第 1 周

### Day 1（周一）—— 搭骨架

**目标：fork 完成，Rust 项目能编译，Git 推上去**

上午：
- [ ] GitHub fork learn-claude-code → 改名 learn-agent-rust
- [ ] clone 到本地
- [ ] 删除 agents/、requirements.txt
- [ ] cargo init，建好项目结构
- [ ] 写 Cargo.toml（4 个依赖：reqwest, serde, serde_json, tokio）
- [ ] 写 src/lib.rs（共享类型：Message, ApiRequest, ApiResponse, ContentBlock）
- [ ] cargo check 通过

下午：
- [ ] 写 src/bin/s01_agent_loop.rs
- [ ] cargo build 通过
- [ ] 设置 ANTHROPIC_API_KEY，cargo run --bin s01
- [ ] 手动测试：输入 "list files in current directory"，确认能跑
- [ ] 重写 README.md（加 credits、Rust 说明、learning path 表格）
- [ ] git push

**交付物：** GitHub 上能看到 Rust 项目，s01 能跑

**Agent 原理：** 理解最基础的 agent loop：用户输入 → 模型回复 → 执行 tool → 把结果还给模型

**Rust 能力：** Cargo 项目结构、serde derive、enum with tag

---

### Day 2（周二）—— 网站部署

**目标：https://learncc.cirray.cn 能打开**

上午：
- [ ] SSH 到 ECS
- [ ] git clone 你的仓库到 /opt/learn-agent-rust
- [ ] cd web && npm install && npm run build
- [ ] pm2 start npm --name "learn-site" -- start -- -p 3000
- [ ] curl http://localhost:3000 确认有响应

下午：
- [ ] 阿里云 DNS：添加 A 记录 learn → ECS IP
- [ ] 阿里云安全组：确认 80/443 放行
- [ ] 写 Nginx 配置 /etc/nginx/sites-available/learn.cirray.cn
- [ ] nginx -t && nginx -s reload
- [ ] 浏览器访问 http://learn.cirray.cn 确认能打开
- [ ] certbot --nginx -d learn.cirray.cn 配 HTTPS
- [ ] 验证 https://learn.cirray.cn 正常

**交付物：** 网站上线，朋友能通过链接访问

> 为什么 Day 2 就部署？先上线再慢慢改。每天的进展都能在线看到，这种"有人能看见"的感觉是坚持下去的重要动力。

---

### Day 3（周三）—— s02 Tool Dispatch

**目标：从硬编码 match 变成 HashMap 动态分发**

上午：读 learn-claude-code 的 s02 文档，理解核心变化：loop 不变，加 tool 只需加一行 handler

- [ ] 定义 Tool trait：

  ```rust
  #[async_trait]
  pub trait Tool: Send + Sync {
      fn name(&self) -> &str;
      fn definition(&self) -> Value;  // JSON schema
      async fn execute(&self, input: Value) -> String;
  }
  ```

- [ ] 实现 BashTool, ReadFileTool, WriteFileTool, EditFileTool（4 个 tool）
- [ ] 用 HashMap<String, Box<dyn Tool>> 做 dispatch

下午：
- [ ] 把 agent_loop 改成从 HashMap 查找 tool 执行
- [ ] cargo run --bin s02 测试
- [ ] 试几个复杂任务："读取 Cargo.toml 的内容然后总结"
- [ ] git push

**交付物：** s02 能跑，4 个工具

**Agent 原理：** tool 的本质是"把模型的意图映射到真实的系统操作"

**Rust 能力：** trait object, Box<dyn Trait>, async_trait, HashMap

---

### Day 4（周四）—— s03 TodoWrite + s04 Subagent

**目标：agent 能先规划再执行，能拆子任务**

上午 s03：
- [ ] 实现 TodoManager struct（Vec<TodoItem> + CRUD 方法）
- [ ] 实现 TodoWriteTool（模型调用这个 tool 来管理计划）
- [ ] 在 system prompt 里加规则："先用 todo_write 列计划，再执行"
- [ ] 测试："帮我创建一个 hello world Rust 项目并运行"
      → 模型应该先列出步骤，再逐个执行

下午 s04：
- [ ] 实现 subagent：独立的 agent_loop，拥有干净的 messages[]
- [ ] 主 agent 可以通过一个 "dispatch_agent" tool 派生子任务
- [ ] 关键：子 agent 的 messages 和主 agent 隔离，不互相污染
- [ ] 测试："分析 src/ 下每个文件的作用，然后写一个总结"
- [ ] git push

**交付物：** s03 + s04 能跑

**Agent 原理：** planning 是 agent 可靠性的核心；subagent 是隔离复杂度的关键手段

**Rust 能力：** struct 方法、Vec 操作、函数递归/嵌套 async

---

### Day 5（周五）—— s05 Skill Loading + s06 Context Compact

**目标：按需加载知识 + 上下文不会爆**

上午 s05：
- [ ] 实现 SkillLoaderTool：读取 skills/ 下的 SKILL.md 文件
- [ ] 把技能内容通过 tool_result 注入（不是塞进 system prompt）
- [ ] 关键理解：知识是运行时按需加载的，不是启动时全量灌入
- [ ] 测试：让 agent 调用一个 skill 然后基于它完成任务

下午 s06：
- [ ] 实现三层压缩策略：
      1. 如果 messages 太长 → 用模型做摘要
      2. 保留最近 N 条原文
      3. 旧消息替换为摘要
- [ ] 简化版：先实现"超过 20 条消息时，把前 10 条压缩成摘要"
- [ ] 测试：跑一个长对话，看压缩是否生效
- [ ] git push

**交付物：** s05 + s06 能跑，前 6 个 session 全部完成

**Agent 原理：** context window 是有限资源，compression 是长对话的生命线

**Rust 能力：** 文件 I/O (std::fs)、字符串处理、Vec 切片操作

---

### Day 6-7（周末）—— 缓冲 + 补债 + 文档

**这两天是安全网，也是沉淀期。**

前 5 天大概率有东西卡住或没做完，但这很正常——遇到障碍、想办法绕过去、再继续，这本身就是成长的一部分。

- [ ] 修复前 5 天遗留的 bug
- [ ] 给 s01-s06 每个文件加完整中文注释
- [ ] 写 docs/zh/ 下的中文文档（至少 s01-s03）
- [ ] 把每个 session 的核心原理写成 README 里的表格
- [ ] 在 ECS 上 git pull + rebuild 网站，确认最新代码在线
- [ ] 如果有余力：开始预习 s07 的任务系统设计

**绝对不要跳过这两天去赶进度。** 没有好注释的代码没人愿意看；没有沉淀的学习很快就会忘。

---

## 第 2 周

### Day 8（周一）—— s07 Task System

**目标：文件持久化的任务 DAG**

- [ ] 设计 Task struct：id, title, status, deps（依赖列表）
- [ ] 实现 TaskManager：CRUD + 依赖解析（拓扑排序）
- [ ] 任务存储为 JSON 文件（serde_json 序列化到磁盘）
- [ ] 实现 task_create, task_list, task_update 三个 tool
- [ ] 测试："把这个项目拆成 5 个子任务并标注依赖关系"
- [ ] git push

**Agent 原理：** 任务图让 agent 从"执行者"升级为"项目管理者"

**Rust 能力：** serde 序列化到文件、图的拓扑排序、Result 错误处理

---

### Day 9（周二）—— s08 Background Tasks

**目标：慢操作后台跑，agent 继续思考**

- [ ] 用 tokio::spawn 在后台执行耗时命令
- [ ] 用 tokio::sync::mpsc channel 通知主循环"任务完成了"
- [ ] agent 不用阻塞等待，可以继续处理其他事情
- [ ] 测试："后台运行 cargo build，同时告诉我项目结构"
- [ ] git push

**Agent 原理：** 并发是 agent 效率的关键，不能让一个慢任务堵死整个系统

**Rust 能力：** tokio::spawn、mpsc channel、Arc<Mutex<T>>

---

### Day 10（周三）—— s09 Agent Teams

**目标：多个 agent 协作**

- [ ] 定义 Teammate struct：name, role, system_prompt
- [ ] 实现 JSONL mailbox（或用 mpsc channel 替代）
- [ ] 主 agent 可以 send_message 给 teammate
- [ ] teammate 收到消息后独立运行自己的 agent_loop
- [ ] 测试："用两个 agent 分工——一个写代码，一个写测试"
- [ ] git push

**Agent 原理：** 单个 agent 有认知边界，团队协作能突破这个边界

**Rust 能力：** 多个 tokio task 并发、channel 通信、struct 组合

---

### Day 11（周四）—— s10 + s11 Protocols + Autonomous

**目标：团队协议 + 自主认领**

上午 s10：
- [ ] 实现 request-response 协议（统一的消息格式）
- [ ] 添加 shutdown 协议和 plan approval 流程
- [ ] 简化版：不需要完整 FSM，用 enum 表示状态即可

下午 s11：
- [ ] 实现 idle cycle：teammate 空闲时自动扫描任务板
- [ ] 自动认领（claim）符合自己角色的任务
- [ ] 不需要 lead 逐个分配
- [ ] git push

**Agent 原理：** 自主性是 agent 团队从"工具"变成"系统"的关键跃迁

**Rust 能力：** enum 状态机、loop + select!、模式匹配

---

### Day 12（周五）—— s12 Worktree Isolation + 集成

**目标：全部 12 个 session 完成**

上午 s12：
- [ ] 每个 teammate 在独立的工作目录下操作
- [ ] 用 task_id 绑定 worktree 路径
- [ ] 隔离文件系统，防止互相干扰
- [ ] 简化版：每个 agent 的 CWD 不同即可，不一定要 git worktree

下午：
- [ ] 写 s_full.rs：把所有 12 个机制组合到一个文件
- [ ] 端到端测试：给一个复杂任务，看完整系统能否协作完成
- [ ] git push

**交付物：** 12 个 session 全部可运行

---

### Day 13（周六）—— 网站改造

**目标：learn.cirray.cn 展示 Rust 代码而非 Python**

- [ ] 研究 web/ 目录结构，理解它怎么读取和展示代码
- [ ] 修改源码查看器：.py → .rs 文件路径
- [ ] 修改代码高亮：Python → Rust 语法高亮
- [ ] 修改首页文案：体现 Rust 特色
- [ ] 去掉原作者的社交链接，换成你的
- [ ] npm run build 本地预览
- [ ] git push
- [ ] ECS 上 git pull + npm run build + pm2 restart

> 如果 web/ 改起来太复杂，可以简化目标：只改首页文案 + README 展示，源码查看器先保持原样。完美是好的敌人。

---

### Day 14（周日）—— 发布日

**目标：一切就绪，对外发布**

上午：
- [ ] 最终检查所有 session 能编译能跑
- [ ] README 最终润色（学习路径表格、每个 session 标 ✅）
- [ ] 确认 https://learn.cirray.cn 网站正常
- [ ] 确认 GitHub 仓库页面干净整洁

下午：
- [ ] 去原仓库提 issue：
      标题："Rust implementation of learn-claude-code"
      内容：简要介绍你的项目，附 GitHub 链接和网站链接，
            请求在 README 的 "What's Next" 部分加一个链接
- [ ] （可选）在 Rust 社区发帖：r/rust, V2EX, Rust 中文社区
- [ ] （可选）写一篇文章/推文介绍你的项目

**交付物：** 项目公开发布

---

## 风险预案

| 如果…… | 怎么办 |
|--------|--------|
| Rust 编译错误卡太久 | 来 Claude Code 解决 |
| s09-s12 太难做不完 | 先写简化版（TODO 注释标明），保证能编译 |
| 网站改造太复杂 | 只改首页文案，不改源码查看器 |
| ECS 部署出问题 | 先用 Vercel 临时托管，域名 CNAME 过去 |
| 某天状态不好 | 周末两天的缓冲就是为这个准备的 |

---

## 每日节奏

```
09:00 - 09:30  读当天 session 的原版代码 + 文档
09:30 - 12:00  写 Rust 实现
12:00 - 13:00  午饭休息
13:00 - 15:00  调试 + 测试
15:00 - 16:00  写注释和文档
16:00 - 16:30  git push + ECS 上更新
16:30 - 17:00  预习明天的 session
```

---

## 最低可交付版本

如果两周结束时没做完全部 12 个 session，**最低标准是：s01-s06 完成 + 网站上线 + README 完整。**

这 6 个 session 已经覆盖了 agent 核心原理：loop, tools, planning, subagent, knowledge, compression。

s07-s12 的 multi-agent 部分可以标为 "🚧 Coming Soon"，后续再补。
一个做了 60% 但质量好的项目，远胜于做了 100% 但粗糙的项目。

---

## 最后

两周之后，不管结果如何，都会对 AI Agent 的工作原理有比现在深得多的理解，Rust 也会从"翻过书本"到"写过工程"。

这件事值得做，现在就开始。
