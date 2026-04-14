+++
title = "记录下这两天Debug项目的问题与思考"
description = "Claude API 的 artifact 渲染在 Cloudflare 和 rendering_mode 之间反复横跳，Sonnet 越改越乱，换 Opus 才理清了真正的矛盾点。"
date = 2026-04-14

[taxonomies]
categories = ["项目"]
tags = ["claude", "opus", "sonnet", "artifact", "cloudflare", "debug"]

[extra]
lang = "zh"
toc = true
+++

项目开始初具代码量规模，大几千行的样子。一个Pro账号已经基本应付不了了。  
昨天花了一整天调一个 bug，Sonnet 每次改动都只会堆砌代码，问题始终没解决。今天换了 `claude --model opus-4-5`，它知道从另外一个角度出发，先去查阅相关技术资料文档，当然token量也在快速增加。

---

## 问题是什么

我在做一个功能：发消息让 Claude 生成 CAD 图纸（SVG/HTML），前端应该显示"正在生成产物"的转圈动画，完成后出现可点击的卡片，点卡片能在 iframe 里预览 HTML。

听起来不复杂，但实际调试时掉进了一个坑：**Cloudflare 和 `rendering_mode` 之间的矛盾**。

---

## rendering_mode 的两难

Claude API 有个 `rendering_mode` 参数：

- 不设 `"raw"` → Claude 返回 `<antArtifact>` 标签格式，前端能正确解析成产物卡片。但 Cloudflare 会拦截请求。
- 设了 `"raw"` → 能绕过 Cloudflare，但 Claude 返回的是普通 markdown 代码块，不是 `<antArtifact>` 格式。

昨天用 Sonnet 反复调试，它的策略是不断在前端代码里加各种兼容逻辑——试图同时处理两种格式、加 fallback、加正则匹配。代码越堆越多，但核心矛盾没解决。

---

## Opus 怎么处理的

换 Opus 之后，它没有继续在前端打补丁，而是直接指出了问题：

> rendering_mode 必须是 "raw" 才能过 Cloudflare，那就接受 markdown 代码块格式，改前端解析逻辑来适配这个格式。

思路清晰，不纠结。与其两头兼顾，不如确定一个约束条件，然后围绕它设计。

---

## 顺手做了一次重构
之前在没有特别说明的情况下，代码都是堆砌到main.rs里的。导致之后改问题通常都会通读一遍这个大文件。我想这可能是我消耗token过快的一部分原因。

这次模块拆分，把臃肿的单文件拆成了多个模块，每个文件 100-300 行。这样修 bug 时只需要读相关模块，token 消耗能降 80% 以上。

代价是：**这次重构瞬间把我 5 小时的 session token limit 烧没了。**

---

## 体会

Sonnet 适合执行明确的任务，但遇到需要判断"该改哪里"的问题时，它倾向于堆代码而不是退一步想清楚。Opus 贵是贵，但在关键的架构判断上确实更靠谱。

另外，之前我都是自己测试，把问题描写清楚，再让claude修改。我觉得这样会省token，但事实证明，这样大概率会更费事，不如让claude自己设计测试方法，自己测试查找问题，它会更清楚问题所在。当然还有些测试场景它还覆盖不了，比如让CC调起本地浏览器来测试。这个以后应该会有办法吧。
