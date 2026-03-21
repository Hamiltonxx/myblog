+++
title = "Claude Code 入门指南：AI 辅助编程从安装到最佳实践"
description = "全面介绍 Claude Code 的核心概念、常用命令、工作原理与最佳实践，帮助你快速上手这款 AI 编程助手。"
date = 2026-03-20

[taxonomies]
categories = ["工具"]
tags = ["claude", "ai", "cli", "开发工具"]

[extra]
lang = "zh"
toc = true
+++

Claude Code 是 Anthropic 推出的 AI 编程助手 CLI，核心理念是让 AI 直接在你的项目目录里工作——读文件、改代码、跑命令、提 PR，全程陪伴。

## 安装与启动

```bash
curl -fsSL https://claude.ai/install.sh | bash

cd your-project
claude
```

进入项目目录后执行 `claude` 即可启动交互会话。

## 常用命令

| 命令 | 说明 |
|------|------|
| `claude` | 启动交互会话 |
| `claude "task"` | 执行一次性任务，如 `claude "fix the build error"` |
| `claude -p "query"` | 单次查询后退出，如 `claude -p "explain this function"` |
| `claude -c` | 继续当前目录最近一次对话 |
| `claude -r` | 恢复历史对话 |
| `claude commit` | 创建 Git commit |
| `/clear` | 清空对话历史 |
| `/help` | 查看所有命令 |
| `exit` / `Ctrl+C` | 退出 |

**快捷键提示：**
- `?` — 查看所有键盘快捷键
- `Tab` — 命令补全
- `↑` — 命令历史
- `/` — 所有命令与技能列表

## Claude Code 的工作原理

### Agentic Loop

Claude Code 的核心是一个三阶段循环：**收集上下文 → 执行操作 → 验证结果**。

这个循环由两个组件驱动：负责推理的模型，以及负责执行的工具集。Claude Code 作为 agentic harness，提供工具调用、上下文管理和执行环境，将语言模型变成真正的编程 Agent。

### 模型选择

- **Sonnet** — 处理大多数编程任务，性价比高
- **Opus** — 更强的推理能力，适合复杂架构决策

切换方式：`/model` 命令，或启动时 `claude --model <name>`。

### 工具系统

没有工具，Claude 只能输出文字；有了工具，它可以读代码、改文件、执行命令、搜索网络、调用外部服务。

内置工具是基础，你还可以通过以下方式扩展：
- **Skills** — 添加可复用的领域知识和工作流
- **MCP** — 连接外部服务
- **Hooks** — 自动化触发脚本
- **Subagents** — 将子任务委托给独立 Agent

### 会话与上下文

每条消息、每次工具调用、每个结果都会存储，支持回退、恢复和分支。Claude 修改文件前会自动创建快照，随时可以撤销。

**上下文窗口**是最重要的资源。对话历史、文件内容、命令输出都在里面，填满后 Claude 的表现会下降。Claude 会自动压缩，但早期的指令可能丢失——把持久规则写进 `CLAUDE.md`，用 `/context` 查看当前占用情况。

### 撤销变更

- **Esc 两次** — 回退到上一个状态
- **"Undo that"** — 告诉 Claude 撤销
- **Shift+Tab** — 循环切换权限模式：默认（编辑前询问）→ 自动接受 → 计划模式

## 扩展 Claude Code

| 扩展方式 | 作用 |
|----------|------|
| `CLAUDE.md` | 每次会话都能看到的持久上下文 |
| Skills | 可复用的知识和可调用的工作流 |
| MCP | 连接外部服务与工具 |
| Subagents | 在独立上下文中运行子任务，返回摘要 |
| Agent teams | 多个独立会话协作，共享任务与点对点通信 |
| Hooks | 在循环外作为确定性脚本运行 |
| Plugins | 打包和分发上述功能 |

### 创建 Skill

在 `.claude/skills/` 目录下创建 Markdown 文件：

```markdown
---
name: fix-issue
description: Fix a GitHub issue
---
Analyze and fix the GitHub issue: $ARGUMENTS.

1. Use `gh issue view` to get the issue details
2. Search the codebase for relevant files
3. Implement the fix
4. Write and run tests
5. Create a descriptive commit and PR
```

然后用 `/fix-issue 1234` 调用。

### 创建自定义 Subagent

在 `.claude/agents/` 目录下定义专用助手：

```markdown
---
name: security-reviewer
description: Reviews code for security vulnerabilities
tools: Read, Grep, Glob, Bash
model: opus
---
You are a senior security engineer. Review code for injection vulnerabilities,
auth flaws, secrets in code, and insecure data handling.
```

然后对 Claude 说："Use a subagent to review this code for security issues."

## 最佳实践

### 先探索，再计划，再编码

直接让 Claude 写代码很容易解决错误的问题。推荐流程：

1. **Explore**：进入 Plan Mode，Claude 只读文件和回答问题，不做修改
2. **Plan**：让 Claude 生成详细的实现计划
3. **Implement**：切回普通模式，按计划编码
4. **Commit**：让 Claude 写描述性 commit 消息并创建 PR

### 提供丰富的上下文

- 用 `@filename` 引用文件，而不是描述文件位置
- 直接粘贴截图到提示框
- 给出 URL
- `cat error.log | claude` — 把文件内容通过管道传给 Claude

### 配置环境

- `/init` — 根据当前项目结构生成 `CLAUDE.md` 模板，之后持续完善
- `claude mcp add` — 连接 Notion、Figma、数据库等外部工具
- 用 Hooks 处理每次都必须执行的操作

### 管理会话上下文

- 任务之间频繁使用 `/clear`
- 用 Subagents 处理调查性任务，避免污染主上下文
- 用 Checkpoints 回退
- 恢复历史对话而不是重新开始

### 自动化与并行扩展

一旦单个 Claude 工作流跑通，可以用并行会话、非交互模式（`claude -p`）和扇出模式成倍放大输出。

---

Claude Code 的核心约束是上下文窗口——理解这一点，其余最佳实践自然就清晰了。
