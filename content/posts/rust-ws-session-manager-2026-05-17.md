+++
title = "SessionManager: 用 DashMap 管理 WebSocket 连接"
description = "多设备、多前端并发接入，消息要路由给对的人——今天把这套会话管理机制从设计到代码全部落地，顺手解了设备重连的竞态。"
date = 2026-05-17

[taxonomies]
categories = ["项目"]
tags = ["rust", "websocket", "dashmap", "session", "tokio", "axum", "concurrency"]

[extra]
lang = "zh"
toc = true
+++

今天做 `wsserver` 的会话管理层：`SessionManager`、`CommandBus`、`AppState`——三个结构串起来，解决了"消息怎么找到对的 WebSocket 连接"这个核心问题。

---

## 问题：Server 同时管着一堆连接，怎么找到对的那个？

这个项目的 Server 有两类 WebSocket 客户端：

- **设备**：拉伸试验机，10KHz 数据上报
- **前端**：浏览器，发控制指令、接收状态

前端发来 `test.start { dst: "device-001" }`，Server 要把这条消息准确投到 `device-001` 的连接上去。设备上报 `test.state_changed`，Server 要广播给所有前端。

这就是会话管理要干的事。

---

## SessionHandle：发消息的"遥控器"

最核心的概念是 `SessionHandle`——拿着它就能向对应客户端发消息：

```rust
// ws/session.rs
#[derive(Clone)]
pub struct SessionHandle {
    pub id: SessionId,       // UUID，连接期间不变
    pub role: Role,
    pub device_id: Option<String>,
    sender: mpsc::Sender<ProtocolMessage>,  // 向写任务投递消息
}

impl SessionHandle {
    pub async fn send(&self, msg: ProtocolMessage) -> Result<...> {
        self.sender.send(msg).await
    }

    pub fn try_send(&self, msg: ProtocolMessage) -> Result<...> {
        self.sender.try_send(msg)
    }
}
```

关键设计：`sender` 对应的 `Receiver` 交给 WebSocket 写任务协程，调用方只管投消息，不直接碰 socket：

```
调用方                      写任务协程
  │  handle.send(msg)          │
  │ ──→ [mpsc channel] ──────→ │ socket.send(msg)
  │ (立即返回)                  │
```

这样广播时不会因为某个慢客户端阻塞整条链路。

---

## SessionManager：双索引的会话池

```rust
// ws/manager.rs
#[derive(Clone)]
pub struct SessionManager {
    inner: Arc<DashMap<SessionId, SessionEntry>>,
    device_index: Arc<DashMap<String, SessionId>>,  // device_id → SessionId
}
```

两张表：
- `inner`：主表，`SessionId → SessionEntry`（含发送端）
- `device_index`：反向索引，`device_id → SessionId`，让 `handle_by_device` 做到 O(1)

**为什么用 DashMap 而不是 `Arc<RwLock<HashMap>>`？**

`RwLock` 每次写操作会锁整个 Map，其他协程全等。DashMap 内部分片，同时只锁 key 所在的那一片，高并发下吞吐量高得多——对于这个 10KHz 上报的场景有实际意义。

---

## 注册与移除

```rust
pub fn register(
    &self,
    role: Role,
    device_id: Option<String>,
    device_type: Option<String>,
    customer: Option<String>,
    queue_size: usize,
) -> (SessionHandle, mpsc::Receiver<ProtocolMessage>) {
    let (sender, receiver) = mpsc::channel(queue_size);
    let id = Uuid::new_v4();

    self.inner.insert(id, SessionEntry { role: role.clone(), device_id: device_id.clone(), ... });

    if role == Role::Device {
        if let Some(ref did) = device_id {
            self.device_index.insert(did.clone(), id);
        }
    }

    (SessionHandle::new(id, role, device_id, sender), receiver)
}
```

`receiver` 返回给连接的写任务协程持有，`SessionHandle` 留在 `SessionManager` 里供路由使用。

---

## 重连竞态：一个容易踩的坑

设备断线重连时，时序可能是：

1. 新连接注册 → `device_index["device-001"] = new_id`
2. 旧连接清理 → `device_index.remove("device-001")` ← 把新的也删了！

解决方式是 `remove_if`，只删"还指向自己"的记录：

```rust
pub fn remove(&self, id: &SessionId) {
    if let Some((_, entry)) = self.inner.remove(id) {
        if entry.role == Role::Device {
            if let Some(ref did) = entry.device_id {
                // 只有索引还指向旧 id 时才删
                self.device_index.remove_if(did, |_, sid| sid == id);
            }
        }
    }
}
```

为此写了一个专门的单元测试：

```rust
#[test]
fn test_reconnect_race_safe() {
    let manager = SessionManager::new();

    let (old_handle, _rx1) = manager.register(Role::Device, Some("device-001".into()), ...);
    let (new_handle, _rx2) = manager.register(Role::Device, Some("device-001".into()), ...);

    manager.remove(&old_handle.id);  // 清旧连接

    let found = manager.handle_by_device("device-001");
    assert!(found.is_some());
    assert_eq!(found.unwrap().id, new_handle.id);  // 新连接还在
}
```

---

## CommandBus：消息路由

`CommandBus` 包在 `SessionManager` 上面，提供高层路由接口：

```rust
impl CommandBus {
    // 广播给所有前端
    pub async fn broadcast(&self, role: Role, message: ProtocolMessage) -> usize { ... }

    // 发给指定设备
    pub async fn send_to_device(&self, device_id: &str, message: ProtocolMessage) -> anyhow::Result<()> { ... }
}
```

广播里有一个小优化：前 N-1 个 `clone`，最后一个直接 `move`，省掉一次不必要的克隆：

```rust
let last = handles.pop().unwrap();
for handle in &handles {
    handle.try_send(message.clone()).ok();
}
last.try_send(message).ok();  // 最后一次 move，不再 clone
```

10KHz 场景下，少一次 `Vec<u8>` clone 是有意义的。

---

## AppState：组装起来

```rust
// state.rs
#[derive(Clone)]
pub struct AppState {
    sessions: SessionManager,
    command_bus: CommandBus,
}

impl AppState {
    pub fn new() -> Self {
        let sessions = SessionManager::new();
        let command_bus = CommandBus::new(sessions.clone());
        Self { sessions, command_bus }
    }

    pub async fn broadcast_to_frontends(&self, msg: ProtocolMessage) -> usize {
        self.command_bus.broadcast(Role::Frontend, msg).await
    }

    pub async fn send_to_device(&self, device_id: &str, msg: ProtocolMessage) -> anyhow::Result<()> {
        self.command_bus.send_to_device(device_id, msg).await
    }
}
```

`AppState` 实现 `Clone`，Axum 的每个请求 handler 拿到的是克隆——但内部全是 `Arc`，克隆代价极低，实际共享同一份数据。

---

## 下一步

有了会话池，下一步实现 WebSocket 连接的完整生命周期——握手验证、读写 loop、断线清理接入 `SessionManager`，把整条链路跑通。
