+++
title = "华为鸿蒙把 AccessibilityService 折腾成什么样了"
description = "在华为 MatePad 上做语音控制微信，踩遍了 rootInActiveWindow、ACTION_PASTE、截图 API 的坑，最后发现国产 ROM 的限制根本不在 API 层。"
date = 2026-03-28

[taxonomies]
categories = ["项目"]
tags = ["android", "accessibility", "harmonyos", "huawei", "wechat", "automation"]

[extra]
lang = "zh"
toc = true
+++

今天做了一个给老人用的语音助手 App——说一句"给儿子发微信说我吃饭了"，自动完成整个流程。目标很简单，但华为鸿蒙把我教做人了。

---

## 项目背景

App 叫 ElderPlay，核心逻辑：
1. 按住悬浮按钮说话（离线语音识别，sherpa-onnx + SenseVoice）
2. LLM 解析意图，提取联系人名和消息内容
3. 用 `AccessibilityService` 自动操作微信完成发送

设备：HUAWEI BAH3-W59（MatePad T8），HarmonyOS，API 29。

---

## 第一坑：`rootInActiveWindow` 跨 App 失效

最早的多轮 Agent 方案：每轮读屏幕节点 → 喂给 LLM → LLM 决定下一步操作。在华为上，一旦切到微信，`rootInActiveWindow` 就返回 null 或空节点，LLM 收到空屏幕，开始乱猜联系人名字（"彭xx"这个真实联系人名完全读不到，模型自己编了一个）。

修复：改用 `getWindows()` 遍历所有窗口，跳过输入法窗口和自身包名：

```kotlin
val wins = windows
for (win in wins) {
    if (win.type == AccessibilityWindowInfo.TYPE_INPUT_METHOD) continue
    val root = win.root ?: continue
    val pkg = root.packageName?.toString() ?: ""
    if (pkg == "com.elderplay.agent") { root.recycle(); continue }
    traverseNode(root, nodes)
    root.recycle()
}
```

这个改了之后，节点确实能读到了，但后来发现这只是开始。

---

## 第二坑：LLM 看不到屏幕，坐标乱点

读到了节点，但 LLM 没有图像，只有文字描述，让它估坐标就是瞎猜。Agent 连续把"xxx前端交流群"和"遵义路xxx互助团购群"当成了目标联系人打开。

于是转向截图方案：让 LLM 看截图再决定操作。

---

## 第三坑：截图 API 一个都用不了

**方案 A：`AccessibilityService.takeScreenshot()`**
需要 API 30+，设备是 API 29，直接跳过。

**方案 B：`Bitmap.wrapHardwareBuffer()`**
需要 API 31+，同上。

**方案 C：`MediaProjection`**
API 21+ 都能用。实现了，加了"开启屏幕录制"按钮，用户点击允许后……App 直接崩了。华为对 `MediaProjection` 的处理明显有问题，`createVirtualDisplay` 后 `ImageReader` 一帧都拿不到，超时5秒返回 null，全部12轮都是"截图不可用"。

最终：**截图方案在这台华为设备上全部失败**。

---

## 转折：放弃通用 Agent，改写死流程

发送微信消息这件事，流程是固定的：

```
打开微信 → 点搜索 → 输入联系人名
→ 读取搜索结果节点 → 让用户确认联系人
→ 点击联系人 → 输入消息 → 点发送
```

不需要 LLM 来导航，LLM 只做一件事：从语音里提取 `contact` 和 `message`。

```kotlin
// CommandParser：一次 LLM 调用
// "跟彭xx说我吃过了" → {"intent":"wechat_send","contact":"彭xx","message":"我吃过了"}

when (cmd.intent) {
    "wechat_send" -> WeChatSender.send(contact, message, ...)
}
```

`WeChatSender` 是8步硬编码流程，每步都是确定性的代码，不再有 LLM 参与导航。

---

## 第四坑：`ACTION_PASTE` 在微信搜索框失效

硬编码流程跑起来了，微信搜索框也打开了，键盘也弹出来了，剪贴板也写进去了（键盘上方能看到"彭xx"的剪贴板建议）。但就是粘不进去。

`ACTION_PASTE` 返回 false，`ACTION_SET_TEXT` 也不行。

搜了一下，发现各品牌的限制对比，总结如下：

| 问题类型 | 华为 | 小米 | OPPO/VIVO | Pixel |
|------|------|------|------|------|
| `rootInActiveWindow` 跨 App | 受限 | 基本可用 | 基本可用 | 完全可用 |
| `ACTION_PASTE` | 通常可用，需正确聚焦 | 可用 | 可用 | 完全可用 |
| `takeScreenshot()` | 受限 | 可用(API30+) | 可用(API30+) | 完全可用 |
| 服务保活 | 极难（PowerGenie） | 较难 | 较难 | 无限制 |

`ACTION_PASTE` 在华为上理论上可用，但要求节点**真正聚焦**。问题可能是调用顺序——要先 `ACTION_FOCUS` 再粘贴。这个还在调试中。

---

## 今天的教训

1. **国产 ROM 的限制不在 API 层，在进程保活和 window 访问层**。`rootInActiveWindow` 不是被禁了，而是 window 焦点判断逻辑不同。

2. **通用 LLM Agent 对固定流程场景是过度设计**。12 轮循环 + LLM 决策，不如8行硬编码可靠。

3. **截图方案对旧华为设备完全不可行**，不是 API 限制，是硬件兼容性问题。

4. **剪贴板粘贴是中文输入的最佳方案**，但依赖节点的聚焦状态，细节很重要。

---

## 下一步

搞定 `ACTION_PASTE` 的聚焦问题（加 `ACTION_FOCUS` 或长按触发粘贴菜单），然后完整跑通"给彭xx发我吃过了"这个流程。

或许真搞不定了。这个计划就流产了。
