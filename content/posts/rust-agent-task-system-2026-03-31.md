+++
title = "给 AI 一个任务清单，它第一反应是用标题当 ID"
description = "今天实现了带依赖关系的任务系统——Kahn 算法、Arc<Mutex<T>>、JSON 持久化都顺手，但最值得记录的是 Claude 调工具时犯的那个错，以及它说明了什么。"
date = 2026-03-31

[taxonomies]
categories = ["项目"]
tags = ["rust", "ai", "claude", "agent", "learn-agent-rust", "task-system", "topological-sort"]

[extra]
lang = "zh"
toc = true
+++

> 今天是 Day 8，目标是给 agent 装上任务系统：任务有依赖、有状态、能排序、能持久化。
>
> 代码层面没什么意外，倒是跑起来之后 Claude 的第一反应让我停下来想了一下。

---

## 先说架构

任务的核心数据结构很简单：

```rust
#[derive(Serialize, Deserialize, Clone)]
struct Task {
    id: String,
    title: String,
    status: TaskStatus,  // Todo / InProgress / Done
    deps: Vec<String>,   // 依赖的 task id 列表
}
```

`TaskManager` 包三件事：

1. **CRUD**：add / update_status / list
2. **持久化**：load 从 `tasks.json` 读，save 写回去
3. **拓扑排序**：Kahn 算法，算出「依赖先于被依赖者」的执行顺序

暴露给 agent 的工具有四个：`create_task`、`update_task`、`list_tasks`、`get_next_tasks`（返回当前可立即开始的任务）。

---

## Rust 里有意思的两个地方

### Arc<Mutex<T>> 共享状态

四个工具都需要访问同一个 `TaskManager`，但工具是 trait object，生命周期各自独立。解法是把 `TaskManager` 包进 `Arc<Mutex<T>>`：

```rust
type SharedManager = Arc<Mutex<TaskManager>>;

struct CreateTaskTool(SharedManager);
struct UpdateTaskTool(SharedManager);
// ...

let manager = Arc::new(Mutex::new(TaskManager::load("tasks.json")));

tools.insert("create_task".to_string(), Box::new(CreateTaskTool(manager.clone())));
tools.insert("update_task".to_string(), Box::new(UpdateTaskTool(manager.clone())));
```

`clone()` 只克隆引用计数，不克隆数据。每个工具执行时 `self.0.lock().unwrap()` 拿锁，用完自动释放。这是 Rust 共享可变状态的标准模式，写起来比想象中自然。

### Kahn 算法

拓扑排序用的是 Kahn（BFS 版），核心是「入度」：

```rust
// 每个任务的入度 = 它的 deps 数量
let mut in_degree: Vec<usize> = self.tasks.iter().map(|t| t.deps.len()).collect();

// 邻接表：dep 完成后，能减少哪些任务的入度
let mut dependents: Vec<Vec<usize>> = vec![vec![]; self.tasks.len()];
for (i, task) in self.tasks.iter().enumerate() {
    for dep in &task.deps {
        if let Some(&j) = index.get(dep.as_str()) {
            dependents[j].push(i);
        }
    }
}

// 入度为 0 的先入队，出队时减少邻居入度
let mut queue: VecDeque<usize> = in_degree.iter().enumerate()
    .filter(|&(_, &d)| d == 0).map(|(i, _)| i).collect();
```

有环时结果长度 < 任务总数，返回 `Err`。

这段编译时踩了一个模式匹配的 bug：

```rust
// 错误写法——Rust 新版拒绝在隐式借用中用 & 解构
.filter(|(_, &d)| d == 0)

// 正确写法
.filter(|&(_, &d)| d == 0)
```

---

## 最值得记录的事

代码写完、编译通过，跑起来输入「帮我规划一个 Rust Web 项目的开发任务」，看 Claude 怎么调工具。

它连续创建了前三个任务（id=1、2、3），然后开始创建有依赖的任务——**把任务标题塞进了 deps**：

```
创建失败: 依赖的任务 id '设计数据库架构与 Schema' 不存在
创建失败: 依赖的任务 id '选择 Web 框架 (Actix-web/Axum/Rocket)' 不存在
```

连续失败了八九个，然后它调了一次 `list_tasks`，看到返回结果里 id 是数字，才明白过来——重新创建，这次全用数字 id，一次成功。

整个过程没有崩溃，最终规划出了完整的 14 个任务、正确的依赖关系、合理的执行顺序。

---

## 这说明了什么

第一反应是「该在 system prompt 里写清楚」。确实，加一句：

> deps 必须填已创建任务的数字 id（如 "1"、"2"），不能填任务标题。

大概率能修掉这个问题。

但更有意思的结论是：**工具的接口就是 API，模糊的接口会产生歧义**。

`deps` 字段名本身不够清晰——「依赖」，依赖什么？标题？id？名字？在人类的语境里，「依赖某个任务」很自然地想到用任务名称来引用，而不是一个数字 id。Claude 犯的不是蠢错，是在做合理推断。

如果字段叫 `dep_ids`，或者 description 写「填 create_task 返回的数字 id」，歧义就消失了。

这和写给人看的 API 文档是一回事，只是调用方变成了模型。

---

## 今天的 Rust 收获

| 机制 | 用在哪 | 解决什么问题 |
|------|--------|-------------|
| `Arc<Mutex<T>>` | 多工具共享 TaskManager | trait object 之间共享可变状态 |
| `Vec::drain` + `VecDeque` | Kahn 算法 | 拓扑排序的队列操作 |
| `serde_json::to_string_pretty` | TaskManager::save | 可读性好的 JSON 持久化 |
| pattern `|&(_, &d)|` | filter 中 | 显式借用避免隐式解构报错 |

---

## 下一步

Day 9 是 S08 Background Tasks——`tokio::spawn` 后台执行耗时命令，`mpsc channel` 通知主循环任务完成。

agent 不阻塞，可以边等边干别的事。终于要进入真正的异步了。

代码在：[https://github.com/Hamiltonxx/learn-claude-code-rust](https://github.com/Hamiltonxx/learn-claude-code-rust)
