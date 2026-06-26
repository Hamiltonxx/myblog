+++
draft = true
title = "氢能站Agent系列4 -- 第二个 Agent"
description = "Multi-Agent 不是堆 crate，在动手之前先扫代码，结果发现 mng-api 已经在跑预警扫描了。记录两件真正有价值的事：修掉 mp-agent 里的假消费数据，以及让 station-agent 做「响应预警」而非「重复检测」。"
date = 2026-06-18

[taxonomies]
categories = ["项目"]
tags = ["rust", "agent", "multi-agent", "sqlx", "postgres", "function-calling"]

[extra]
lang = "zh"
toc = true
+++

这是一个多 Agent 系统，在开始第二个 Agent 之前, 把现在 Agent 工程代码整体再浏览一遍。

---

## 先搞清楚现在站在哪里

扫 `analytics-agent/src/chat.rs`，发现 `/chat` 接口并不是直接把问题塞给 LLM：

```rust
// 第一次非流式请求：让 DeepSeek 判断是否需要调用工具
let routing = state.llm.chat_with_tools(&req.messages, &tools).await?;
let tool_call = routing.tool_calls.as_ref().and_then(|calls| {
    calls.iter().find(|c| {
        c.function.name == QUERY_TOOL || c.function.name == DISPATCH_TOOL
    })
});
```

每次对话，先把历史消息 + 工具定义一起发给 DeepSeek，让它决定：**这个问题需要查数据库，还是直接闲聊？**

命中工具就走数据管线（NL→SQL→结果→流式回答），没命中就直接流式回答。用户问"我们有几个站"，DeepSeek 调 `query_hydrogen_business_data`，查的是真实数据库。**这已经是工具调用了，不是 RAG，不是 few-shot。**

现有工具一共两个：

| 工具 | 干什么 |
|---|---|
| `query_hydrogen_business_data` | NL→SQL，查任意业务数据 |
| `plan_hydrogen_dispatch` | 调度规划，返回候选车+候选罐 |

这个结论影响了后续所有决策：既然工具调用已经通了，**Multi-Agent 的增量价值在于分治，而不在于「能查数据」这件事**。单 Agent 跑不好的场景，才值得拆。

---

## 改动一：mp-agent 消费报表接真实数据

`mp-agent` 是给小程序车主用的。扫到 `consumption_report` 函数：

```rust
fn consumption_report(q: &str) -> String {
    let period = if q.contains("上月") { "上月" } else { "本月" };
    format!(
        "<b>{period}</b>加氢消费摘要：<br>\
        累计加注 <b>32 kg</b><br>\
        合计支出 <b>¥1,241.60</b><br>\
        均价 <b>¥38.80/kg</b><br>\
        出行 <b>11 次</b><br>\
        最常去：虹桥示范站"
    )
}
```

硬编码假数据。这段代码大概率是占位符，得先改一下。

**改法分两步。**

第一步，`ChatBody` 加 `uid` 字段——小程序端知道当前用户是谁，把 uid 传过来：

```rust
#[derive(Deserialize)]
pub struct ChatBody {
    pub q: String,
    pub lat: Option<f64>,
    pub lng: Option<f64>,
    pub uid: Option<String>,   // 新增：车主 users.uid
    pub history: Vec<HistMsg>,
}
```

第二步，`consumption_report` 改成异步函数，查 `refuel_orders` 真实记录：

```rust
async fn consumption_report(state: &AppState, uid: &str, q: &str) -> String {
    if uid.is_empty() {
        return "请先登录，再查看你的消费记录。".into();
    }

    let (start, end, label) = period_range(q);  // 按关键词算时间范围

    let summary = sqlx::query_as::<_, ConsumptionSummary>(
        "SELECT
           CAST(COUNT(*) AS bigint) AS trips,
           CAST(COALESCE(SUM(actual_h2_kg), 0) AS float8) AS total_kg,
           CAST(COALESCE(SUM(total_amount), 0) AS float8) AS total_amount,
           CAST(CASE WHEN SUM(actual_h2_kg) > 0
                THEN SUM(total_amount) / SUM(actual_h2_kg)
                ELSE 0 END AS float8) AS avg_price
         FROM refuel_orders
         WHERE driver_user_id = $1
           AND order_status = 'completed'
           AND completed_at >= $2
           AND completed_at < $3
           AND deleted_at IS NULL",
    )
    .bind(uid).bind(start).bind(end)
    .fetch_one(&state.pool)
    .await;
    // ...
}
```

时间段的计算用 `chrono`：

```rust
fn period_range(q: &str) -> (DateTime<Utc>, DateTime<Utc>, &'static str) {
    let now = Utc::now();
    if q.contains("上月") || q.contains("上个月") {
        let (year, month) = if now.month() == 1 {
            (now.year() - 1, 12u32)
        } else {
            (now.year(), now.month() - 1)
        };
        let start = Utc.with_ymd_and_hms(year, month, 1, 0, 0, 0).single().unwrap_or(now);
        let end   = Utc.with_ymd_and_hms(now.year(), now.month(), 1, 0, 0, 0).single().unwrap_or(now);
        (start, end, "上月")
    } else if q.contains("近七天") || q.contains("近7天") {
        (now - Duration::days(7), now, "近 7 天")
    } else {
        let start = Utc.with_ymd_and_hms(now.year(), now.month(), 1, 0, 0, 0).single().unwrap_or(now);
        (start, now, "本月")
    }
}
```

最常去哪个站，再发一条查询：

```rust
let top_station: Option<String> = sqlx::query_scalar(
    "SELECT station_name FROM refuel_orders
     WHERE driver_user_id = $1
       AND order_status = 'completed'
       AND completed_at >= $2 AND completed_at < $3
       AND deleted_at IS NULL AND station_name != ''
     GROUP BY station_name ORDER BY COUNT(*) DESC LIMIT 1",
)
.bind(uid).bind(start).bind(end)
.fetch_optional(&state.pool).await
.unwrap_or(None);
```

这次就算用户加氢记录真的是 0 条，也会如实返回"本月暂无加氢记录"，而不是永远给同一个假数字。

---

## 改动二：station-agent 的定位转了一次

原计划：新建 `station-agent` crate，定时扫描低库存站点，写入 `supply_alert_events`。

写完 `monitor.rs`，准备提交，顺手看了眼 mng-api 的 `supply_chain.go`：

```go
func (s *supplyChainService) StartJobs() {
    go func() {
        s.ScanAlerts()
        t := time.NewTicker(2 * time.Minute)
        defer t.Stop()
        for range t.C {
            s.ScanAlerts()  // 每 2 分钟扫一次
        }
    }()
    // ...
}
```

`ScanAlerts()` 里：查各站点真实储量，扣掉近期已锁定的预约预估消耗，低于安全下限就写 `supply_alert_events`。**逻辑比我写的还要精细**——它还会估算「几小时后跌破下限」，区分 `warning` 和 `urgent`。

如果我的 `station-agent` 也往同一张表写，预警就会重复，运营人员每次看到的都是两条一样的记录。

所以改了定位：**station-agent 不做预警检测，改为响应预警**。

mng-api 扫出预警，但它不会自动建 `supply_request`（补给需求单），还是要运营人员手动操作。station-agent 填补这个空白——轮询 `supply_alert_events` 里 `status=active` 且没有 `supply_request_id` 的记录，自动建草稿单。

```rust
async fn find_pending_alerts(pool: &PgPool) -> anyhow::Result<Vec<PendingAlert>> {
    sqlx::query_as::<_, PendingAlert>(
        "SELECT event_id, station_id, enterprise_id
         FROM supply_alert_events
         WHERE status = 'active'
           AND (supply_request_id IS NULL OR supply_request_id = '')
           AND deleted_at IS NULL
         ORDER BY created_at ASC
         LIMIT 20",
    )
    .fetch_all(pool).await
    .map_err(Into::into)
}
```

建草稿单有个麻烦：需求单号是 `SRQ_yyyyMMdd0001` 格式的流水号，两个 goroutine/异步任务同时写就会冲突。

解法是 **PostgreSQL advisory lock**：

```rust
let mut tx = pool.begin().await?;

// 事务内的 advisory lock，事务结束自动释放
// 所有写需求单的路径都用同一个 lock key，串行化编号生成
sqlx::query("SELECT pg_advisory_xact_lock(hashtext('supply_request_no'))")
    .execute(&mut *tx).await?;

let request_no: String = sqlx::query_scalar(
    "SELECT 'SRQ_' || TO_CHAR(NOW(), 'YYYYMMDD') || LPAD(
         (SELECT COALESCE(COUNT(*), 0) + 1
          FROM supply_requests
          WHERE request_no LIKE 'SRQ_' || TO_CHAR(NOW(), 'YYYYMMDD') || '%'
            AND deleted_at IS NULL
         )::text, 4, '0'
     )",
)
.fetch_one(&mut *tx).await?;
```

`hashtext('supply_request_no')` 把字符串变成整数用作 lock key，同一个 key 在同一时刻只有一个事务能持有。不同服务（station-agent 和 mng-api 自己）都用这个 key，编号就不会撞车。

插完需求单，把预警状态改成 `converted` 并写入 `supply_request_id`，下次轮询就不会重复处理：

```rust
sqlx::query(
    "UPDATE supply_alert_events
     SET supply_request_id = $1, status = 'converted', updated_at = NOW()
     WHERE event_id = $2",
)
.bind(&request_id).bind(&alert.event_id)
.execute(&mut *tx).await?;

tx.commit().await?;
```

这样整条链路变成：

```
mng-api ScanAlerts()（每 2 分钟）
   → 写 supply_alert_events（status=active）
         ↓
station-agent（每 120 秒轮询）
   → 发现 active + 无 supply_request 的预警
   → 自动建草稿 supply_request
   → 预警更新为 converted
         ↓
运营人员
   → 在管理端看到草稿单，选工厂、确认价格，提交
```

---

## 关于 Multi-Agent，今天得到的结论

Multi-Agent 不是「多写几个 crate」，而是**分治**：把超出单 Agent 可靠处理范围的任务，拆给专注的多个角色。

衡量标准很简单：如果一句话能说清楚某个 Agent 的职责边界，它就值得存在。

- `analytics-agent`：把自然语言翻译成 SQL，查业务数据 ✓
- `mp-agent`：给车主回答附近站点和个人消费 ✓
- `station-agent`：响应低库存预警，自动建补给草稿单 ✓

三个 Agent，三条清晰的边界。还没动手的「Orchestrator」要等到一个问题需要同时跨越两个以上 Agent 时再说——过早的路由层只会让调试变成噩梦。

下一步：让 analytics-agent 的调度工具从「只读建议」变成「确认后落单」——这才是 Agent 从「说话」到「做事」的关键一跳。
