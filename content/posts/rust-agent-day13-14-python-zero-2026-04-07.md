+++
title = "用 Rust 学 AI Agent——Day 13-14：代码全写完了，仓库还不是 Rust 项目"
description = "以为把源码改成 Rust 就算完成了，结果 docs、README、skills 里全是 Python——最后一公里比想象中远。"
date = 2026-04-07

[taxonomies]
categories = ["项目"]
tags = ["rust", "ai-agent", "documentation", "refactor", "github"]

[extra]
lang = "zh"
toc = true
+++

12 个 session 全部跑通，代码推上去，以为项目就算收尾了。然后去看了眼 GitHub 的语言统计——Python 还占着一席之地。

原因很简单：这个项目是从原版 Python 实现 fork 来的。源码换成了 Rust，但文档、README、示例文件全都是原版的。一个自称 Rust 实现的仓库，docs 里展示的是 Python agent loop，README 还在教人 `pip install`，快速开始命令还是 `python agents/s01_agent_loop.py`。

---

## 这种割裂有多明显

网站首页的核心模式区域，展示的是 agent loop 的代码片段。视觉上已经换成了 Rust 高亮，但副标题描述还是通用的，没有提 Rust。

docs/ 目录里 s05 到 s12，中英文各一份，代码块里全是 Python。读者打开文档想了解某个机制的实现，看到的是 Python 类定义和 `def` 语法——和仓库里的 Rust 源码对不上。

最藏得深的是 `skills/agent-builder/` 目录。里面有四个参考实现文件：`minimal-agent.py`、`tool-templates.py`、`subagent-pattern.py`，还有一个 `init_agent.py` 用来生成新 agent 项目的骨架——全是 Python，直接继承自原项目，没有动过。

---

## 最后一公里做了什么

**把 skills 里的 Python 全部换成 Rust。**

`minimal-agent.py` 是最重要的参考文件，展示了最小可用 agent 的完整实现。Rust 版本反而更短——Python 版靠 class 和 dict 组织数据，Rust 版用 `struct` + `serde_json`，去掉了所有动态类型的噪音：

```rust
async fn agent(prompt: &str, history: &mut Vec<Message>, ...) -> String {
    history.push(Message { role: "user".into(), content: json!(prompt) });
    loop {
        let resp = call_api(client, api_key, history).await;
        if resp.stop_reason.as_deref() != Some("tool_use") { break; }
        // 执行工具，追加结果...
    }
}
```

`init_agent.py`（生成项目骨架的脚本）换成了 `init_agent.sh`，内嵌生成 `Cargo.toml` 和 `main.rs` 的逻辑。

**docs 里的代码块统一换成 Rust，运行命令换成 `cargo run --bin`。**

**README-zh 和 README-ja 里的核心模式展示换成 Rust agent loop，快速开始换成：**

```sh
git clone https://github.com/Hamiltonxx/learn-claude-code-rust
cd learn-claude-code-rust
export ANTHROPIC_API_KEY=sk-xxx
cargo run --bin s01_agent_loop
```

---

## 结果

```bash
find . -name "*.py" -not -path "./web/node_modules/*"
# (空)
```

GitHub 语言统计：Python 0%。

---

整个过程让我意识到，"用 Rust 重写"和"这是一个 Rust 项目"之间，差的不只是源码。文档是项目的门面，读者第一眼看到的是文档，不是 `src/`。一个 Rust 项目的文档里展示 Python 代码，就像一家日料店菜单上全是川菜介绍——菜可能确实很好，但信号是混乱的。

项目地址：[github.com/Hamiltonxx/learn-claude-code-rust](https://github.com/Hamiltonxx/learn-claude-code-rust)
