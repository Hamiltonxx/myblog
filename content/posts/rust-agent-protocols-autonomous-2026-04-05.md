+++
title = "用 Rust 学 AI Agent——Day 11：不再等指令的 agent"
description = "今天给 agent 装上了两样东西：统一的消息协议（让通信有迹可查），和自主认领任务的能力（让 agent 主动干活而不是等着被叫）。"
date = 2026-04-05

[taxonomies]
categories = ["项目"]
tags = ["rust", "agent", "tokio", "state-machine", "mpsc", "arc-mutex", "learn-agent-rust", "llm"]

[extra]
lang = "zh"
toc = true
+++

> Day 11，两个 session：S10 定协议，S11 让 agent 自己找活干。
>
> 做完之后我才意识到，这两件事本质上是同一件事——**从「被动响应」到「主动行动」**。

---

## 之前的问题

前几天的 agent teams 能跑，但有个隐患：**agent 之间传的是裸字符串**。

主 agent 给 coder 发消息，是一个 `&str`。coder 返回结果，也是一个 `String`。出了问题想调试？没有 from，没有 to，没有类型，只有字符串内容本身。

这在两个 agent 的时候还好，一旦扩展到五个、十个，调用链一复杂，你根本不知道这条消息从哪来、要到哪去、是任务还是结果还是信号。

S10 要解决的就是这个——**给通信装上格式**。

---

## AgentMessage：一个 enum 值描述一条消息

```rust
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
enum AgentMessage {
    Task { from: String, to: String, content: String },
    Result { from: String, to: String, content: String },
    PlanRequest { from: String, plan: String },
    PlanApproval { approved: bool, reason: Option<String> },
    Shutdown { reason: String },
}
```

五种消息类型，穷尽了 agent 之间所有有意义的交互。每一条消息现在都是结构化的——谁发的、发给谁、什么类型。

打印出来是这样的：

```
[Task] user -> coordinator: 帮我写一个排序函数
[Task] coordinator -> coder: 写一个 O(n log n) 的 Rust 排序实现
[Result] coder -> coordinator: fn merge_sort(arr: &mut Vec<i32>) { ... }
```

同样的 `send_message` 调用，现在每一步都有据可查。

---

## Protocol：agent 的状态不只是「运行中」

做协议的时候，我意识到一件事：**agent 的状态比我以为的复杂**。

它不是只有「运行」和「停止」两种状态。它可能：
- 正常跑（Idle）
- 提交了一个计划，在等用户审批（AwaitingApproval）
- 收到了关闭信号，在做收尾（ShuttingDown）
- 彻底终止了（Terminated）

这些状态之间的转换是有规则的——Idle 收到 PlanRequest 才能进 AwaitingApproval，任意状态收到 Shutdown 都进 ShuttingDown。

用 enum + `transition()` 方法把规则写死：

```rust
impl Protocol {
    fn transition(self, msg: &AgentMessage) -> Self {
        match (self, msg) {
            (Protocol::Idle, AgentMessage::PlanRequest { plan, .. }) =>
                Protocol::AwaitingApproval { plan: plan.clone() },

            (Protocol::AwaitingApproval { .. }, AgentMessage::PlanApproval { approved: true, .. }) =>
                Protocol::Idle,

            (_, AgentMessage::Shutdown { reason }) =>
                Protocol::ShuttingDown { reason: reason.clone() },

            (state, _) => state,
        }
    }
}
```

`match (当前状态, 消息)` 的二元组穷尽了所有合法转换。漏掉一种情况，编译器会提醒你。这是 Rust 的 enum 比其他语言的状态机好用的地方——**非法状态在类型层面就无法表达**。

---

## 计划审批：有副作用的操作不能偷偷执行

S10 里加了一个 `request_plan_approval` 工具。agent 在执行写文件、运行命令这类有副作用的操作前，必须先调这个工具，把计划给用户看：

```
[计划审批] Agent 提交了以下计划:
1. 创建 src/sort.rs
2. 写入 merge_sort 实现
3. 在 main.rs 里调用并测试

是否批准？(y/n):
```

用户说 y，agent 继续。说 n，agent 重新规划。

这个模式在真实产品里很重要。一个 agent 拿到「帮我整理一下文件夹」这个指令，如果直接开干，可能删掉你以为没用但其实很重要的东西。**先展示计划，再执行**——这不是功能，是信任机制。

---

## S11：别叫我，我自己来拿活

S10 的 agent 还是被动的——等主 agent 通过工具调用它，它才干活。

S11 想做的是：**teammate 主动扫描任务板，看到匹配自己角色的任务就认领**。

任务板是一个共享状态：

```rust
type TaskBoard = Arc<Mutex<Vec<Task>>>;
```

每个任务有一个 `role_hint`（coder / reviewer / any）和一个 `status`（Open / InProgress / Done）。

认领操作要原子完成——加锁、找任务、改状态、解锁：

```rust
fn board_claim(board: &TaskBoard, role: &str) -> Option<Task> {
    let mut tasks = board.lock().unwrap();
    for task in tasks.iter_mut() {
        if task.status == TaskStatus::Open
            && (task.role_hint == role || task.role_hint == "any")
        {
            task.status = TaskStatus::InProgress { claimed_by: role.to_string() };
            return Some(task.clone());
        }
    }
    None
}
```

为什么要在锁里把状态改完再返回？防止两个 teammate 同时看到同一个 Open 任务，都以为自己认领了。**先改状态，再放锁**——这是经典的 test-and-set。

---

## loop + select!：同时监听两件事

每个 teammate 是一个独立的 `tokio::spawn` task，用 `select!` 在两件事之间切换：

```rust
loop {
    tokio::select! {
        _ = sleep(POLL_INTERVAL) => {
            // 每隔 2 秒扫一次任务板
            if let Some(task) = board_claim(&board, &role) {
                println!("[{}] 认领任务 #{}: {}", name, task.id, task.title);
                let result = run_task(&client, &api_key, &system_prompt, &task.title).await;
                board_complete(&board, task.id, &result);
            }
        }
        _ = shutdown.recv() => {
            println!("[{}] 收到关闭信号，退出。", name);
            break;
        }
    }
}
```

`select!` 的语义是：**哪个 future 先 ready，就执行哪个分支**。这让 teammate 同时具备了「定时工作」和「响应关闭」两种能力，没有任何忙等，没有额外线程。

和普通的 `loop + sleep` 相比，区别在于：如果 `shutdown` channel 有消息，`select!` 会立刻打断 sleep 响应，不需要等到下一个轮询周期。这在实际系统里很重要——你不会希望发了关闭信号还要等两秒。

---

## 主 agent 的角色变了

在 S09，主 agent 是「指挥官」——它主动找 coder、找 reviewer，一步步协调。

在 S11，主 agent 变成了「项目经理」——它负责拆任务、往任务板上加条目，至于谁来做、什么时候做，它不管。teammate 自己会去抢。

```
用户: 帮我用 Rust 写一个排序库，包含文档和测试

Agent 拆任务 → add_task("实现 merge_sort", role_hint="coder")
             → add_task("写单元测试", role_hint="coder")
             → add_task("审查代码质量", role_hint="reviewer")
             → add_task("补充文档注释", role_hint="any")

[coder] 认领任务 #1: 实现 merge_sort
[coder] 认领任务 #2: 写单元测试
[reviewer] 认领任务 #3: 审查代码质量
[coder] 完成任务 #1
...
```

主 agent 不需要知道 coder 什么时候空闲，也不需要等 coder 完成再派下一个任务——**任务板是解耦的媒介**。这个模式有个名字：生产者-消费者，或者更时髦的叫法，工作队列（work queue）。

---

## 今天的 Rust 收获

| 概念 | 用在哪 |
|------|--------|
| `enum` 状态机 + `match` 穷尽 | Protocol 状态转换，非法状态编译期报错 |
| `Arc<Mutex<T>>` | TaskBoard 在多个 teammate 间共享 |
| `tokio::spawn` | 每个 teammate 是独立的异步 task |
| `loop + select!` | 同时监听定时轮询和 shutdown 信号 |
| `mpsc::channel` | 主线程向每个 teammate 发送关闭信号 |

---

## 一个没想到的感悟

做 S11 的时候，我想到了一件事：**这和人类团队的工作方式其实很像**。

好的团队不是事事需要经理点头——成员知道自己擅长什么，主动去任务板上领符合自己专长的活，做完了标记完成，再去领下一个。经理的工作是拆任务、定优先级、看全局，而不是盯着每个人的每一步。

agent 也可以这样工作。这不只是工程上的解耦，也是一种组织方式。

---

## 下一步

Day 12：S12 Worktree Isolation——每个 teammate 在独立的工作目录下操作，防止互相干扰。然后写 `s_full.rs`，把全部 12 个机制组合到一个文件，跑一次端到端测试。

十二天，十二个机制，一个能干活的 Rust agent。快了。

代码在：[https://github.com/Hamiltonxx/learn-claude-code-rust](https://github.com/Hamiltonxx/learn-claude-code-rust)
