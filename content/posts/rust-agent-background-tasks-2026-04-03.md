+++
title = "用 Rust 学 AI Agent——Day 9：让 agent 同时做两件事，我踩了哪些异步的坑"
description = "今天实现了后台任务系统——tokio::spawn + mpsc channel，agent 启动耗时命令后可以继续对话。但这条路上有几个坑，几乎每个 Rust 异步新手都会踩。"
date = 2026-04-03

[taxonomies]
categories = ["项目"]
tags = ["rust", "tokio", "async", "mpsc", "agent", "learn-agent-rust", "background-tasks"]

[extra]
lang = "zh"
toc = true
+++

> Day 9，目标是让 agent 能「后台跑命令、前台继续聊」。
>
> 核心只有两件事：`tokio::spawn` 丢任务到后台，`mpsc channel` 通知结果回来了。
> 听起来简单，但这段路上的坑，几乎每个 Rust 异步新手都会踩一遍。

---

## 我想要的效果

用户说「后台跑 `sleep 5 && echo done`，我先去问你别的问题」，agent 回「好，任务 id=bg-1，已启动」——然后继续响应下一个问题。五秒后，主循环打印一行：

```
[后台通知] bg-1 完成 | done
```

没有阻塞，没有等待，像真正的后台进程一样。

---

## 架构一句话

```
用户输入 → agent loop → run_background tool
                               ↓
                          tokio::spawn（异步子任务）
                               ↓（完成后）
                          tx.send((id, output))
                               ↓
主循环 try_recv() → 打印通知
```

`BgStore`（`Arc<Mutex<HashMap>>`）存任务状态，`CompletionTx`（`mpsc::UnboundedSender`）传完成信号。工具执行时注册任务、spawn 后台跑，立即返回任务 id 给 Claude。

---

## 坑一：`std::process::Command` 把整个运行时卡死了

最开始我习惯性地写：

```rust
let out = std::process::Command::new("sh")
    .arg("-c").arg(&command)
    .output()
    .unwrap();
```

编译通过，运行也「正常」——但后台任务执行期间整个 agent 完全没有响应。

原因：`std::process::Command::output()` 是**同步阻塞**调用。tokio 的线程池虽然是多线程的，但 async 任务调度依赖「任务在 .await 时让出控制权」。一旦某个任务开始同步阻塞，它占着线程不放，直到命令结束。

正确写法是换成异步版本：

```rust
use tokio::process::Command;

let out = Command::new("sh")
    .arg("-c").arg(&command)
    .output()          // 这里返回的是 Future
    .await;            // 等待时让出控制权
```

`tokio::process::Command` 在底层用的是 epoll/kqueue，等待子进程时不占线程。**在 tokio 里，所有 I/O 和进程操作都应该用 tokio 的异步版本，而不是标准库的同步版本。**

---

## 坑二：`Arc<Mutex<T>>` 锁不能跨 `.await`

把 `Arc<Mutex<TaskManager>>` 传进 spawn 的闭包，然后在里面写：

```rust
tokio::spawn(async move {
    let mut store = self.store.lock().unwrap(); // 拿锁
    // ... 一些操作
    let out = Command::new("sh").output().await; // ← 编译报错！
    store.entry(id).and_modify(|t| t.status = Done);
});
```

Rust 编译器会报：

```
`std::sync::MutexGuard<...>` cannot be held across an `await` point
```

原因是：`.await` 时当前 async 任务可能被挂起，切换到另一个线程继续执行。而 `std::sync::MutexGuard` 不是 `Send`——它绑定了原始线程，不能跨线程移动。

解法有两种：

**方案 A**：拿锁、操作、立刻释放，不跨 await：

```rust
tokio::spawn(async move {
    // 先 drop 锁再 await
    {
        let mut store = shared_store.lock().unwrap();
        store.insert(id.clone(), BgTask { status: Running, .. });
    } // guard 在这里 drop

    let out = Command::new("sh").output().await; // 现在安全

    let mut store = shared_store.lock().unwrap(); // 再次拿锁
    store.entry(id).and_modify(|t| t.status = Done(result));
});
```

**方案 B**：换成 `tokio::sync::Mutex`（异步锁），它的 guard 实现了 `Send`。代价是每次 lock 要 `.await`，性能略低。

我用的是方案 A——锁住、改状态、立刻释放，简单直接。

---

## 坑三：发送者提前 drop，接收者立刻收到关闭信号

第一版代码里，`tx` 是在 `main` 里创建的，然后 `clone` 一份传给工具。但我把原始 `tx` 存在了一个局部变量里，函数执行完就 drop 了：

```rust
let (tx, mut rx) = mpsc::unbounded_channel();
// ... 把 tx.clone() 传给工具

// tx 本身没有被保留，离开作用域后 drop
// 此时 channel 的发送端引用计数归零
// rx.recv() 立刻返回 None
```

现象是：后台任务还没跑完，主循环就停止接收通知了。

修法：把原始 `tx` 也传进工具结构体，让工具持有一个克隆，`main` 也持有一份（或者干脆不 drop 原始的）：

```rust
let (tx, mut rx) = mpsc::unbounded_channel();

tools.insert("run_background".to_string(), Box::new(RunBackgroundTool {
    store: store.clone(),
    tx,        // ← 把所有权移进工具，工具活着 tx 就活着
    next_id,
}));

// 但注意：工具内部 spawn 时需要 tx.clone()
// 因为 spawn 的闭包要 move tx，下次调用就没了
```

工具内部：

```rust
async fn execute(&self, input: Value) -> String {
    let tx = self.tx.clone(); // clone 一份给 spawn
    tokio::spawn(async move {
        // ...
        let _ = tx.send((id, result, is_error));
    });
    "后台任务已启动".to_string()
}
```

---

## 坑四：`recv()` vs `try_recv()`——一个字母的区别让主循环卡死

主循环需要在「等待用户输入」的同时「响应后台通知」。我最初写的是：

```rust
loop {
    // 检查后台通知
    if let Ok(msg) = rx.recv().await { // ← 错了
        println!("[后台通知] ...");
    }

    // 读用户输入
    let mut line = String::new();
    stdin().read_line(&mut line).unwrap();
```

`rx.recv().await` 是**异步等待**——如果 channel 里没消息，它会一直挂着，永远不会走到 `read_line`。

正确的用法是 `try_recv()`，非阻塞，没消息立即返回 `Err(TryRecvError::Empty)`：

```rust
loop {
    // 非阻塞：有通知就打印，没有就继续
    while let Ok((id, out, err)) = rx.try_recv() {
        let label = if err { "失败" } else { "完成" };
        println!("\n[后台通知] {} {} | {}", id, label,
            out.lines().next().unwrap_or(""));
    }

    // 然后等用户输入
    print!("> ");
    let mut line = String::new();
    stdin().read_line(&mut line).unwrap();
```

当然，`read_line` 本身是同步阻塞的，用户不输入就卡在这里，后台通知只有下次用户回车才能打印出来。这是 demo 级别的实现，生产级别会用 `tokio::select!` 同时监听多个源，但那是 Day 10 以后的事了。

---

## 坑五：spawn 要求 `'static` + `Send`

把本地变量的引用传进 `tokio::spawn`：

```rust
let command = "sleep 3".to_string();
tokio::spawn(async {
    println!("{}", command); // ← 借用了外部变量
});
```

编译报错：

```
captured variable cannot escape `FnOnce` closure body
```

`tokio::spawn` 要求闭包里的所有数据都是 `'static`（自己拥有生命周期，不依赖外部引用）且 `Send`（可以跨线程移动）。

解法是 `move` 闭包，把需要的数据 clone 进去：

```rust
let command = "sleep 3".to_string();
let store = self.store.clone();    // Arc clone
let tx = self.tx.clone();         // Sender clone
let id = id.clone();

tokio::spawn(async move {         // move：把 command/store/tx/id 全部 move 进来
    // 现在这些变量都被 spawn 的任务拥有，'static 满足
});
```

**规律：凡是要进 spawn 的东西，要么是 `Arc<T>` 克隆引用计数，要么是 `Clone` 拷一份，要么直接 move 所有权。**

---

## 最终效果

```
=== S08 Background Tasks ===
输入 exit 退出

> 后台跑 sleep 3 && echo hello
[工具] run_background
    -> 后台任务已启动，id=bg-1
Claude: 好的，已在后台启动命令，任务 id 是 bg-1。你可以继续聊，完成后我会通知你。

> 今天天气怎么样
Claude: 我无法获取实时天气信息，不过你可以查手机天气应用...

[后台通知] bg-1 完成 | hello
```

三秒后通知出来，对话没有卡顿。

---

## 今天的 Rust 收获

| 问题 | 错误写法 | 正确写法 |
|------|----------|----------|
| 后台执行命令 | `std::process::Command` | `tokio::process::Command` |
| 跨 await 持锁 | 拿锁后 .await | 拿锁 → 操作 → 立即 drop → await |
| channel 发送端消失 | tx 局部变量 | tx 移进工具，spawn 时 clone |
| 主循环轮询通知 | `rx.recv().await` | `rx.try_recv()` |
| spawn 捕获变量 | 借用引用 | move + clone Arc |

---

## 下一步

Day 10 是 S09 Agent Teams——多个 agent 并发跑，通过 channel 互相通信。

到时候 `tokio::select!` 该登场了，同时监听用户输入、后台通知、队友消息，真正的多路并发。

代码在：[https://github.com/Hamiltonxx/learn-claude-code-rust](https://github.com/Hamiltonxx/learn-claude-code-rust)
