+++
title = "说「帮我打开微信」，微信真的开了——从零到 Android 语音 Agent 的第一天"
description = "今天把上篇的想法真的跑起来了：一个 Android 平板，一个悬浮按钮，说话，Claude 理解，微信打开。记录这个过程里所有激动人心和踩坑的瞬间。"
date = 2026-03-27

[taxonomies]
categories = ["项目"]
tags = ["android", "accessibility", "claude", "kotlin", "agent", "harmonyos"]

[extra]
lang = "zh"
toc = true
+++

上篇我写了为什么要做这件事——给父母造一个说话就能用的手机。今天，它第一次跑起来了。

不是模拟，不是 demo，是真的在一台华为平板上，按下一个悬浮按钮，Claude 理解了指令，微信打开了。

我盯着 Logcat 里那行 `打开 App: com.tencent.mm`，愣了几秒。

---

## 从零开始有多零

今天开始之前，我：

- 没装 Android Studio
- 没有 Android 手机或平板（用来调试）
- 没写过 Kotlin

唯一有的是：一台华为 MatePad BAH3-W59，一个中转的 Claude API Key，和上篇博客里那个架构图。

装 Android Studio 下载了 1.3G。等待期间研究 Accessibility Service 能干什么——结论是**远比我想象的强大**。

---

## Accessibility Service 到底有多强

这是今天最值得单独讲的部分。

很多人以为 Accessibility Service 是给盲人用的屏幕朗读功能。实际上，它给你的权限是：

**完整的 UI 树访问权限 + 任意操作注入**

具体来说，它能做到：

- 读取屏幕上每一个 View 的文字、位置、是否可点击、resource ID
- 知道当前在哪个 App 的哪个 Activity
- 模拟点击任意坐标或任意文字节点
- 向输入框注入文字
- 模拟手势（滑动、长按）
- 调用系统操作（返回、Home、截图）

没有沙盒限制。微信、美团、任何 App，都在它面前透明。

我写的核心读屏函数长这样：

```kotlin
fun dumpScreenNodes(): List<UiNode> {
    val root = rootInActiveWindow ?: return emptyList()
    val nodes = mutableListOf<UiNode>()
    traverseNode(root, nodes)
    root.recycle()
    return nodes
}

private fun traverseNode(node: AccessibilityNodeInfo, result: MutableList<UiNode>) {
    val bounds = Rect()
    node.getBoundsInScreen(bounds)

    val text = node.text?.toString() ?: ""
    val desc = node.contentDescription?.toString() ?: ""
    val label = text.ifEmpty { desc }

    if (label.isNotEmpty() || node.isClickable || node.isEditable) {
        result.add(UiNode(
            label = label,
            resourceId = node.viewIdResourceName ?: "",
            className = node.className?.toString() ?: "",
            bounds = bounds,
            isClickable = node.isClickable,
            isEditable = node.isEditable,
            isScrollable = node.isScrollable
        ))
    }

    for (i in 0 until node.childCount) {
        val child = node.getChild(i) ?: continue
        traverseNode(child, result)
        child.recycle()
    }
}
```

读出来的结果是这样的：

```
[按钮] "✓ 悬浮窗权限已开启" bounds=[64,913][1136,1073]
[按钮] "✓ 无障碍服务已开启" bounds=[64,1113][1136,1273]
[文字] "一切就绪，可以说话了" bounds=[64,774][1136,913]
```

这就是 Claude 能"看到"的屏幕。点击操作：

```kotlin
fun clickByText(text: String): Boolean {
    val root = rootInActiveWindow ?: return false
    val nodes = root.findAccessibilityNodeInfosByText(text)
    for (node in nodes) {
        if (node.isClickable) {
            node.performAction(AccessibilityNodeInfo.ACTION_CLICK)
            return true
        }
        // 有时候可点击的是父节点
        val parent = node.parent
        if (parent?.isClickable == true) {
            parent.performAction(AccessibilityNodeInfo.ACTION_CLICK)
            return true
        }
    }
    return false
}
```

输入文字：

```kotlin
fun inputText(text: String): Boolean {
    val node = findEditableNode(rootInActiveWindow ?: return false)
    val args = Bundle()
    args.putCharSequence(
        AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE,
        text
    )
    return node?.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args) ?: false
}
```

---

## 悬浮按钮：老人随时能摸到的入口

老人不会"打开一个 App 然后点一个按钮"。入口必须永远在屏幕上。

悬浮按钮用 `WindowManager` 创建，挂在系统层，任何 App 上面都能看到：

```kotlin
val params = WindowManager.LayoutParams(
    220, 220,
    WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
    WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE,
    PixelFormat.TRANSLUCENT
).apply {
    gravity = Gravity.BOTTOM or Gravity.END
    x = 40
    y = 200
}
windowManager.addView(floatingButton, params)
```

按住变色（橙色），松手触发指令。UI 反馈让老人知道"它在听"：

```kotlin
floatingButton.setOnTouchListener { _, event ->
    when (event.action) {
        MotionEvent.ACTION_DOWN -> {
            floatingButton.text = "说话\n中..."
            floatingButton.setBackgroundColor(Color.parseColor("#CCFF5722")) // 橙色
        }
        MotionEvent.ACTION_UP -> {
            floatingButton.text = "按住\n说话"
            floatingButton.setBackgroundColor(Color.parseColor("#CC2979FF")) // 蓝色
            AgentController.execute(userInput, this)
        }
    }
    true
}
```

---

## 踩坑实录

### 坑一：华为 HarmonyOS 是 API 29，不是 30

我把 `minSdk = 30`，结果安装时报"解析包时出现问题"。

华为 MatePad 跑的是 HarmonyOS 3.0，但底层 Android API 是 **29**，不是 30。`takeScreenshot()` 需要 API 30，所以加了版本判断：

```kotlin
fun takeScreenshot(callback: TakeScreenshotCallback) {
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
        takeScreenshot(Display.DEFAULT_DISPLAY, mainExecutor, callback)
    }
}
```

### 坑二：FloatingButtonService 没注册到 Manifest

服务没注册，`startForegroundService()` 当然失败。Logcat 报：

```
Unable to start service Intent { cmp=com.elderplay.agent/.FloatingButtonService }
```

加上就好了：

```xml
<service
    android:name=".FloatingButtonService"
    android:exported="false"
    android:foregroundServiceType="specialUse" />
```

这种错误犯了不奇怪，但 Logcat 一下就能定位，Android 开发体验还是很好的。

### 坑三：华为没有 Google 语音识别

`SpeechRecognizer.createSpeechRecognizer(this)` 在华为上报：

```
SecurityException: Not allowed to bind to service Intent
```

华为 HarmonyOS 没有 Google 服务，系统自带的语音识别服务不对第三方开放绑定。

暂时跳过了语音识别，用硬编码的测试指令替代：

```kotlin
val testInput = "帮我打开微信"
AgentController.execute(testInput, this)
```

先跑通整个链路，语音识别后面接百度/讯飞 SDK。

### 坑四：Claude 返回了 Markdown 代码块

Claude 的响应长这样：

```
\`\`\`json
[
  {"action":"open_app","package":"com.tencent.mm"}
]
\`\`\`
```

直接 `JSONArray(text)` 会崩。加三行 strip：

```kotlin
val text = responseText
    .removePrefix("```json")
    .removePrefix("```")
    .removeSuffix("```")
    .trim()
```

### 坑五：华为会杀掉后台服务

无障碍服务反复被系统清掉。解决方案：

1. 把 ElderPlay 加入启动管理白名单（设置 → 应用启动管理 → 手动管理，三个开关全开）
2. `FloatingButtonService` 用 `startForeground()` 跑前台服务，系统不会随意清掉

---

## Claude 的 Prompt 设计

这是整个 Agent 的核心：把"老人说的话"和"屏幕上有什么"一起发给 Claude，让它生成操作序列。

System prompt：

```
你是一个 Android 手机助手，帮助老人通过语音控制手机。
根据用户的指令和当前屏幕状态，生成一系列操作步骤。

可用操作（JSON 格式）：
- {"action":"open_app","package":"包名"} — 打开 App
- {"action":"click_text","text":"按钮文字"} — 点击包含该文字的按钮
- {"action":"input_text","text":"输入内容"} — 在当前输入框输入文字
- {"action":"press_back"} — 返回
- {"action":"press_home"} — 回主页
- {"action":"swipe_up"} — 向上滑动
- {"action":"wait","ms":1000} — 等待毫秒数

返回格式：只返回 JSON 数组，不要任何解释文字。
```

User message：

```
用户说：帮我打开微信

当前屏幕内容：
[文字] "一切就绪，可以说话了"
[按钮] "✓ 悬浮窗权限已开启"
[按钮] "✓ 无障碍服务已开启"
```

Claude 返回：

```json
[
  {"action": "open_app", "package": "com.tencent.mm"}
]
```

执行器：

```kotlin
when (action.getString("action")) {
    "open_app" -> {
        val pkg = action.getString("package")
        val intent = context.packageManager.getLaunchIntentForPackage(pkg)
        intent?.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        context.startActivity(intent)
    }
    "click_text" -> service.clickByText(action.getString("text"))
    "input_text" -> service.inputText(action.getString("text"))
    "press_back"  -> service.pressBack()
    "press_home"  -> service.pressHome()
    "swipe_up"    -> service.swipeUp()
    "wait"        -> delay(action.optLong("ms", 1000))
}
```

---

## 那一行 Logcat

整个链路通的那一刻，Logcat 打印了这些：

```
D AgentController: 收到指令: 帮我打开微信
D AgentController: 当前屏幕节点数: 3
D AgentController: Claude 响应: {"content":[{"text":"[{\"action\":\"open_app\"...}]"...}]}
D AgentController: 执行 1 个操作
D AgentController: 打开 App: com.tencent.mm
```

然后平板上，微信打开了。

我知道这距离"说话控制手机"还很远——语音识别没接，多步骤没做，微信里怎么找联系人发消息还没写。但这一刻，**整个通路是活的**。

指令进去，Claude 理解，Android 执行。这个循环跑通了。

---

## 现在的架构

```
[悬浮按钮 - 按住]
    ↓
[语音识别 - 待接入]
    ↓ 当前用硬编码文字测试
[AgentController]
    ├── 读屏幕 UI 树 (ElderAccessibilityService.dumpScreenNodes)
    ├── 发给 Claude API
    └── 执行返回的 Action Plan
         ├── open_app → PackageManager.getLaunchIntent
         ├── click_text → AccessibilityNodeInfo.ACTION_CLICK
         ├── input_text → ACTION_SET_TEXT
         └── press_back/home → performGlobalAction
```

四个文件，七百行 Kotlin，一台吃灰多年的平板，一个晚上的时间。

---

## 下一步

1. **语音识别**：接百度语音 SDK，在华为上跑通"按住说话"
2. **多步骤 Agent 循环**：执行一步后重新读屏，再决策，直到任务完成
3. **第一个真实任务**："给儿子发微信说我吃饭了"——需要打开微信、找联系人、输入、发送，四步连续操作

上篇结尾我说"先把导航跑通"，结果晚上直接跑通了微信。

总是比预期的快，Claude Code就是这么让人欲罢不能。

---

> 项目名 ElderPlay，代码在本地，等跑稳了再开源。
