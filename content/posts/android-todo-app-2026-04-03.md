+++
title = "放弃 Claude Code 转战 Gemini：两天踩坑后，我终于把 Android Todo App 做出来了"
date = 2026-04-03
description = "用 AI 写 Android 的正确姿势不是一个 AI 全包——我用 Claude Code 生成界面骨架，再让 Android Studio 的 Gemini 修坑，最终跑通了一个颜值不错的 Kotlin Todo App。"

[taxonomies]
categories = ["项目"]
tags = ["android", "kotlin", "jetpack-compose", "claude-code", "gemini", "todo"]

[extra]
lang = "zh"
toc = true
+++

两天、两台测试机、无数次 rebuild，Accessibility Service 的问题我始终没解决。我决定先放下这块，重新拾起 Android 开发——从一个能跑起来的 Todo App 开始。

这次的策略变了：**让 Claude Code 出 UI 和基础代码，报错后交给 Android Studio 里的 Gemini 来修**。效果出乎意料地好。

---

## 为什么对 Claude Code 感到失望

说实话，我对 Claude Code 做 Android 开发抱了不小的期待。Kotlin 语法它写得很流畅，Jetpack Compose 的组件结构也基本对，但一旦涉及系统级权限和服务——比如 Accessibility Service——就开始抓瞎。

症状很典型：代码看起来没问题，manifest 权限也加了，但服务就是注册不上，或者注册上了又无响应。换了一台测试机，问题还在。两天下来，我意识到这类"真机 + 系统服务"的调试场景，纯靠 AI 聊天根本不够——它看不到 logcat，感知不到设备状态。

暂时搁置，先做能做的事。

---

## 新策略：Claude Code 打底，Gemini 修坑

我把任务拆成两段：

1. **Claude Code 负责架构和 UI 骨架**：数据模型、ViewModel、Compose 布局，整体结构一次出来，省去大量体力活
2. **Android Studio Gemini 负责上下文调试**：它在 IDE 里，能看到完整项目结构、报错信息、依赖版本，修依赖冲突和编译报错比纯聊天精准很多

这个分工非常顺。Claude Code 的输出质量其实不差，问题在于 **修错需要上下文**，而 Gemini 正好有这个优势。

---

## 最终效果

Trello 深蓝风格，分组展示 Overdue 和 Today 任务，勾选完成有删除线，逾期任务左侧红色边框标注。

![Todo App 截图](/images/todo-app-2026-04-03.png)

核心功能：
- [x] Overdue / Today 任务分组
- [x] 点击勾选 + 蓝色填充 + 删除线
- [x] 逾期任务红色左边框
- [x] 彩色 Tag 标签（Work / Learning / Health / Life / Rust）
- [x] FAB 弹出 BottomSheet 添加任务
- [ ] 滑动删除（下一步）
- [ ] Room 数据库持久化（下一步）

---

## 项目结构

```
cn.cirray.todoapp
├── Task.kt           # 数据模型 + Tag 颜色映射
├── TodoViewModel.kt  # StateFlow 状态管理
├── TodoScreen.kt     # 全部 Compose UI
└── MainActivity.kt   # 入口
```

刻意保持平铺，没有过度分层。等接 Room 再拆。

---

## 几个值得记的细节

**Tag 颜色方案**

Tag chip 用原色 22% 透明度做背景，文字用原色——有颜色区分但不抢眼：

```kotlin
val bg   = tag.color().copy(alpha = 0.22f)
val text = tag.color()
```

**Overdue 左边框**

不用 border 参数，直接一个细 `Box`：

```kotlin
Box(
    modifier = Modifier
        .width(3.dp)
        .height(40.dp)
        .clip(RoundedCornerShape(2.dp))
        .background(UrgentRed)
)
```

**Gemini 帮我修掉的坑**

- `material-icons-extended` 没加，`Icons.Default.Add` 报 Unresolved reference
- `lifecycle-viewmodel-compose` 要在 `libs.versions.toml` 声明别名才能引用
- 真机字号偏小，标题从 13sp 调到 16sp

这三个坑在 IDE 里有报错信息，Gemini 一眼就定位了，纯聊天模式下大概率要来回猜。

---

## 下一步

接 Room 做持久化，加滑动删除手势（Compose 的 `SwipeToDismiss`）。

Accessibility Service 那块还没放弃——等 Todo App 跑稳了再回头研究，心态会好很多。
