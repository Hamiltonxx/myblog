+++
title = "写了个自动套利机器人，首次开仓"
description = "从零开始做资金费率套利：策略选择、OKX API 接入、账户踩坑全记录，小白也能看懂。"
date = 2026-04-08

[taxonomies]
categories = ["项目"]
tags = ["rust", "okx", "arbitrage", "crypto", "trading-bot"]

[extra]
lang = "zh"
toc = true
+++

今天干了一件之前一直想做但没动手的事：用 Rust 写了个加密货币套利机器人，从零开始，当天真实开仓。

踩了不少坑，但最后跑通了。把过程记下来，给同样想搞量化但不知道从哪下手的人参考。

---

## 为什么选资金费率套利

套利有很多种：交易所间价差、三角套利、DeFi 闪电贷……但大多数都要跟 HFT 军备竞赛，拼网速拼服务器，个人根本打不过。

**资金费率套利不一样**，它：

- 不拼速度，每 8 小时结算一次
- 逻辑极简：现货持仓 + 合约对冲，赚中间的费率
- 市场中性，BTC 涨跌跟你没关系

原理一句话：

> 永续合约为了锚定现货价格，每 8 小时向多头或空头收费。费率为正时，多头付钱给空头。我们同时持有现货多头 + 合约空头，价格涨跌对冲掉，只收费率。

当前 BTC-USD-SWAP 费率 **0.01% / 8小时**，年化约 **11%**，比大多数理财强。

---

## 进场和离场条件

```
积极进场：费率 ≥ 0.008%（每8小时）→ 年化约 9%
离场：    费率 < 0（转负，开始亏钱）
```

历史数据看，过去 24 天约有一半时间费率在门槛以上，不会等太久。

---

## 用 Rust 写了什么

项目结构很简单：

```
coin/
├── src/
│   ├── main.rs          # 主循环：监控费率 + 自动开平仓
│   └── okx/
│       ├── client.rs    # OKX API 封装（签名、请求）
│       └── trade.rs     # 开仓、平仓、查持仓
├── .env                 # API Key（不提交）
└── Cargo.toml
```

**核心逻辑**就是一个 loop：

```rust
loop {
    let rate = fetch_funding_rate("BTC-USD-SWAP").await?;

    if !in_position && rate >= ENTRY_THRESHOLD {
        open_short(&client, "BTC-USD-SWAP", 7).await?;
        in_position = true;
    } else if in_position && rate < EXIT_THRESHOLD {
        close_short(&client, "BTC-USD-SWAP", 7).await?;
        in_position = false;
    }

    sleep(Duration::from_secs(60)).await;
}
```

每分钟检查一次，费率达标自动开仓，费率转负自动平仓。重启后会先查持仓状态，不会重复开单。

OKX API 签名用 HMAC-SHA256：

```rust
let msg = format!("{}{}{}{}", timestamp, method, path, body);
let sign = STANDARD.encode(HmacSha256::new(key).chain(msg).finalize());
```

---

## 踩了哪些坑

**坑1：账户模式不对**

OKX 默认是「简单模式」（acctLv=1），只能买现货，API 下合约单直接报错 51010。

要在 App 里切换到「**合约模式**」才行：App → 资产 → 账户模式设置 → 合约模式。

**坑2：合约类型选错**

BTC-USDT-SWAP（USDT 本位）需要 USDT 做保证金，但账户里只有 BTC。

换成 **BTC-USD-SWAP（币本位/反向合约）**，用 BTC 做保证金，问题解决。

两者对比：

| 合约 | 保证金 | 适合 |
|------|--------|------|
| BTC-USDT-SWAP | USDT | 有稳定币 |
| BTC-USD-SWAP | BTC | 只有BTC ✅ |

**坑3：合约张数计算**

BTC-USD-SWAP 每张 = 100 USD，不是按 BTC 数量算的。

0.01 BTC × $71,600 ≈ $716 ÷ 100 = **7 张**

---

## 实际开仓与平仓

19:00 开仓，7 张 BTC-USD-SWAP 空单，对应 0.01 BTC 现货：

```json
{ "ordId": "3461036017797177344", "sMsg": "Order placed" }
```

机器人开始每分钟监控费率。

23:00，费率转负，自动平仓：

```
>>> 费率转负，平仓...
>>> 平仓成功，订单号: 3461422255951816352
```

**持仓 4 小时，首战失败。**

---

## 复盘

```
开仓手续费：约 ¥3.5
平仓手续费：约 ¥3.5
期间收到资金费：0（4小时内没有结算点）
净亏损：约 ¥7
```

亏在哪：进场后费率就一路跌，4 小时内没遇到结算时间（每 8 小时一次），手续费还没捂热就被止损出场了。

**但 ¥7 换来的东西：**

- 整套流程从零跑通：API 签名、账户模式、合约类型、开平仓
- 自动止损逻辑真实验证有效，费率转负机器人自己跑路，没有手动干预
- 踩完了所有坑，下次可以直接用

---

## 下一步

- 把程序部署到树莓派，24 小时稳定运行
- 监控多个合约，哪个费率高就做哪个
- 加报警：费率异常或开平仓失败时发通知

Rust 写这种常驻进程确实爽，编译完直接跑，内存占用极低，比 Python 省心多了。
