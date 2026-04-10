+++
title = "用PWA赶紧让用户体验起来"
description = "苹果开发者账号续费卡住了，逼出了一套更快触达用户的方案——反而比 App 更顺滑。"
date = 2026-04-10

[taxonomies]
categories = ["项目"]
tags = ["pwa", "mobile", "next.js", "debug", "ios", "ux"]

[extra]
lang = "zh"
toc = true
+++

今天本来打算把 Cirray 的 AI 对话页面上架 App Store。结果卡在了第一步——开发者账号续费。 我的apple id是美区的，住址是中国的。要我改信息。去改呢又说得让Holder同意!? 去申请了客服，要两个工作日回复。  

放弃了。转头做 PWA。现在反而觉得这条路更对。

---

## 想上架 App Store，然后被现实教育了

计划很美好：把 `/chat` 页面包一层 WebView，走审核，上架，用户下载，完美。

现实是：苹果开发者账号 $99/年，续费页面报错，客服要等 2 个工作日回复，还不知啥时能解决。

等不起。Agent一天，世上一年。我不能因为一个上架问题把发布卡死。我得尽快让用户体验反馈。

---

## 转向 PWA：比我想象的顺多了

PWA（Progressive Web App）的核心是：让网页能像 App 一样安装到主屏幕，全屏运行，有图标，有启动画面。

需要的东西：
1. `manifest.json` — 告诉浏览器这是个可安装的 App
2. HTTPS — 已经有了
3. 图标 — 重新设计了一个黑洞风格的 SVG

```json
{
  "name": "Cirray",
  "start_url": "/chat",
  "display": "standalone",
  "background_color": "#020617",
  "theme_color": "#020617"
}
```

`display: standalone` 这一行是关键——加了它，从主屏幕打开就没有浏览器地址栏，和原生 App 视觉上没区别。

---

## 移动端 bug 一锅端

把产品推给第一批用户之前，我在移动端实测了一遍，发现了几个让人抓狂的问题：

**1. 点输入框，整个页面放大**

iOS 的"贴心"设计：input 字体小于 16px，自动触发页面缩放。

修法很简单，但不明显——所有 input 和 textarea 从 `text-sm`（14px）改成 `text-base`（16px）。同时在 layout 里加：

```ts
export const viewport: Viewport = {
  maximumScale: 1,
};
```

**2. 三指拖动选文本失败**

这个花了不少时间，还是没解决。 Claude Code对一些前端和移动端的细节问题稍有欠缺。
先跳过吧，不太严重。

**3. iPhone 底部 Home 条遮挡输入栏**

用 `env(safe-area-inset-bottom)` 处理安全区域：

```css
.pb-safe {
  padding-bottom: max(12px, env(safe-area-inset-bottom));
}
```

---

## 用户引导：微信扫码 → PWA

发布渠道是微信群，用户扫码进来是微信内置浏览器，不支持直接"添加到主屏幕"。

所以第一次访问我会检测环境，分情况引导：

- **微信浏览器** → 提示"点右上角 ··· → 在浏览器中打开"
- **Safari 未安装** → 提示分享 → 添加到主屏幕
- **已安装 standalone** → 直接进，不打扰

检测代码：

```ts
const isSafari = /^((?!chrome|android|crios|fxios|MicroMessenger|QQ|Weibo).)*safari/i.test(ua);
const isStandalone = window.matchMedia("(display-mode: standalone)").matches;
```

引导页里放了一个实际操作的 GIF，比文字步骤直观多了。

---

## 图标也重新设计了

之前的图标是个"C->"，又丑又糊。 

重新设计了一版：C 弧模拟黑洞吸积盘，一束光横穿而过。纯 SVG，四层叠加出发光厚度感——外层蓝色弥散、中层蓝白、白色核心、青白内缘热点。

最后用 sharp 转成 PNG 给 apple-touch-icon 用。

---

## 这条路比 App Store 更适合现在

回头想想，就算开发者账号顺利，App Store 审核也要 1-2 周，还可能被拒。

PWA 今天改完，明天就能让用户用上。移动端体验和原生 App 几乎没区别，还省了 $99。

等哪天真的需要推 App Store 了，再说。现在先把产品送到用户手里才是正经事。
