+++
title = "工控 Rust WebSocket协议层的设计"
description = "工业测试仪器的 WebSocket 服务要同时处理低频 JSON 指令和 10KHz 二进制数据流，两者的格式差异决定了协议层的核心设计思路。"
date = 2026-05-15

[taxonomies]
categories = ["项目"]
tags = ["rust", "websocket", "protocol", "serde", "binary-protocol", "axum"]

[extra]
lang = "zh"
toc = true
+++
近来要做材料检测工控项目，今天把 `wsserver` 工程的协议层（`common/protocol` crate）从零实现到测试通过。

---

## 背景：服务要同时和两类客户端说话

这个项目是工业拉伸试验机的后端服务，WebSocket 上挂着两类连接：

- **设备**（STM32 / 模拟器）：上报传感器数据、发送状态事件
- **前端**（Vue 界面）：发控制指令、接收实时曲线

如果两类连接各用各的格式，server 里会到处是 if-else。解法是在 `common/` 下放一个共用的 `protocol` crate，server 和 simulator 都引用它，不重复定义。

---

## 两条数据通道，分开设计

### JSON Envelope（控制消息）

低频消息（每秒几次到几十次）：握手、指令、状态通知、响应。格式统一用一个"信封"结构：

```json
{
  "ver": "3.0",
  "id": "42",
  "ts": 1716123500000,
  "src": "frontend-main",
  "dst": "device-001",
  "type": "cmd",
  "name": "test.start",
  "data": { "standard_id": "GB/T 228.1-2021" }
}
```

`type` 只有三种：`cmd`（指令）/ `rsp`（响应）/ `evt`（单向事件）。`src` 的前缀决定了发送方角色：`device-` 开头是设备，`frontend-` 开头是前端，server 靠这个路由消息。

### 二进制帧（高频传感器数据）

JSON 有格式开销，10KHz 的力-位移数据绝对不能走 JSON。算一下：

```
16 bytes header + 8 通道 × 6 bytes = 64 bytes/帧
64 × 10000 帧/s = 640 KB/s
```

WebSocket 承受没问题，但解析必须快。帧结构：

```
┌── 4 bytes ──┬─ 1 ─┬─ 1 ─┬─── 2 ───┬─── 4 ────┬─── 4 ───┐
│  "ICT!"     │ ver │flags│  count  │  seq_no  │ reserved│
└─────────────┴─────┴─────┴─────────┴──────────┴─────────┘
  然后每个通道 6 bytes: stream_id(2) + f32 value(4)
```

`seq_no` 是检测丢帧的关键：server 收到帧序号跳跃就知道链路出问题了，会打 warn 日志并计数，但不会补帧。

---

## 代码解读：`common/protocol/src/lib.rs`

### 角色和消息类型枚举

```rust
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Role {
    Device,
    Frontend,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum MsgType {
    Cmd,
    Rsp,
    Evt,
}
```

`rename_all = "lowercase"` 让 `MsgType::Cmd` 序列化成 `"cmd"` 而不是 `"Cmd"`，和协议约定对齐。`Role` 用 `snake_case` 是为了和 JSON 里的字符串风格一致。

### Envelope 结构体——serde 注解是关键

```rust
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Envelope {
    #[serde(default = "default_version")]   // ①
    pub ver: String,
    pub id: String,
    pub ts: u64,
    pub src: String,
    #[serde(skip_serializing_if = "Option::is_none")]  // ②
    pub dst: Option<String>,
    #[serde(rename = "type")]               // ③
    pub msg_type: MsgType,
    pub name: String,
    #[serde(default, skip_serializing_if = "Value::is_null")]  // ④
    pub data: Value,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub code: Option<i32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub msg: Option<String>,
}

fn default_version() -> String {
    "3.0".to_string()
}
```

四个关键注解逐条说明：

① **`#[serde(default = "default_version")]`**  
反序列化时，如果 JSON 里没有 `"ver"` 字段，调用 `default_version()` 填充。用函数而不是 `Default` 是因为 `String::default()` 返回空字符串，我们需要返回 `"3.0"`。

② **`#[serde(skip_serializing_if = "Option::is_none")]`**  
`dst` 是可选的——不是所有消息都有明确的接收方（比如设备广播事件）。加这个注解后，`dst: None` 序列化时 JSON 里就不会出现 `"dst"` 字段，而不是出现 `"dst": null`。

③ **`#[serde(rename = "type")]`**  
字段名必须用 `msg_type` 因为 `type` 是 Rust 关键字，但协议要求 JSON key 是 `"type"`，`rename` 解决这个冲突。

④ **`#[serde(default, skip_serializing_if = "Value::is_null")]`**  
`data` 是 `serde_json::Value`，反序列化时 JSON 没有 `data` 字段就填 `Value::Null`（`default` 的效果），序列化时 `Null` 就不输出（`skip_serializing_if`）。两个注解配合，让 `data` 字段变成"真正可选"。

### 内部消息枚举

```rust
#[derive(Debug, Clone)]
pub enum ProtocolMessage {
    Json(Envelope),
    Binary(Vec<u8>),
}
```

这个枚举**不实现 Serialize/Deserialize**——它只在 server 内部的 channel 里传递，是已经解析好的结构，不需要再序列化。注释里标注了这一点。

### 二进制帧：parse_frame 和 build_frame

```rust
pub fn parse_frame(data: &[u8]) -> Option<(u32, Vec<(u16, f32)>)> {
    if data.len() < FRAME_HEADER_SIZE { return None; }
    if &data[0..4] != &FRAME_MAGIC { return None; }  // 校验魔数

    let stream_count = u16::from_le_bytes([data[6], data[7]]) as usize;
    let seq_no = u32::from_le_bytes([data[8], data[9], data[10], data[11]]);

    let expected_len = FRAME_HEADER_SIZE + stream_count * 6;
    if data.len() < expected_len { return None; }  // 防截断帧

    let mut streams = Vec::with_capacity(stream_count);
    for i in 0..stream_count {
        let offset = FRAME_HEADER_SIZE + i * 6;
        let stream_id = u16::from_le_bytes([data[offset], data[offset + 1]]);
        let value = f32::from_le_bytes([
            data[offset + 2], data[offset + 3],
            data[offset + 4], data[offset + 5],
        ]);
        streams.push((stream_id, value));
    }
    Some((seq_no, streams))
}
```

几个设计细节：

- 返回 `Option` 而不是 `Result`——解析失败就是 `None`，调用方直接 `?` 或 `if let` 处理，不需要具体错误信息
- `Vec::with_capacity(stream_count)`：提前分配，避免 push 时扩容
- 全程用 `from_le_bytes`，和帧格式约定的小端序对应
- 三道防线：长度检查 → 魔数校验 → 实际数据长度验证，避免读越界

`build_frame` 是 `parse_frame` 的逆操作，主要给模拟器用：

```rust
pub fn build_frame(seq_no: u32, streams: &[(u16, f32)]) -> Vec<u8> {
    let mut buf = Vec::with_capacity(FRAME_HEADER_SIZE + streams.len() * 6);
    buf.extend_from_slice(&FRAME_MAGIC);
    buf.push(0x01);   // version
    buf.push(0x00);   // flags
    buf.extend_from_slice(&(streams.len() as u16).to_le_bytes());
    buf.extend_from_slice(&seq_no.to_le_bytes());
    buf.extend_from_slice(&[0u8; 4]);  // reserved

    for (id, value) in streams {
        buf.extend_from_slice(&id.to_le_bytes());
        buf.extend_from_slice(&value.to_le_bytes());
    }
    buf
}
```

### 测试验证

```rust
#[test]
fn test_envelope_serialize() {
    let env = Envelope { dst: None, msg_type: MsgType::Evt, /* ... */ };
    let json = serde_json::to_string(&env).unwrap();
    assert!(!json.contains("\"dst\""));        // None 不出现在 JSON 里
    assert!(json.contains("\"type\":\"evt\"")); // rename 生效
}

#[test]
fn test_frame_roundtrip() {
    let streams = vec![(0u16, 1.5f32), (1u16, 2.5f32)];
    let frame = build_frame(42, &streams);
    let (seq, parsed) = parse_frame(&frame).unwrap();
    assert_eq!(seq, 42);
    assert_eq!(parsed[0], (0, 1.5));
    assert_eq!(parsed[1], (1, 2.5));
}
```

`cargo test -p protocol` 全绿。

---

## Cargo Workspace 结构

```
wsserver/
├── Cargo.toml           # workspace root
├── common/
│   └── protocol/        # 共用协议 crate
│       ├── Cargo.toml
│       └── src/lib.rs
└── server/
    └── backend/         # 实际服务 crate
        └── Cargo.toml   # protocol = { path = "../../common/protocol" }
```

`server/backend` 的依赖：`protocol`（本地路径）+ `tokio` + `axum` + `tracing` + `clap` + `anyhow`。协议层完全解耦，下一步实现 WebSocket handler 时直接 `use protocol::*` 就行。

---

下一步是会话管理——追踪哪个设备在线、向指定设备发消息。有了今天这层干净的协议抽象，session 层只需要关心 `ProtocolMessage` 枚举，不用再关心字节怎么解析。
