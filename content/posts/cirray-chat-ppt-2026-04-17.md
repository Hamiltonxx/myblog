+++
title = "用纯 HTML 做的 Cirray Chat PPT"
description = "给 Cirray Chat 做了一套演示幻灯片，全程用 HTML+CSS 写，再用 Playwright + python-pptx 导出 pptx，比 PowerPoint 顺手多了。"
date = 2026-04-17

[taxonomies]
categories = ["项目"]
tags = ["html", "pptx", "presentation", "neumorphic", "cirray", "claude"]

[extra]
lang = "zh"
toc = false
+++

给 Cirray Chat 的参赛做了一套演示PPT，全程用 HTML+CSS 写幻灯片，暗色 Neumorphic 风格，键盘翻页，最后用 Playwright 截图 + python-pptx 导出 .pptx。

以下是完整的 12 张幻灯片：

---

![第 1 张 — 封面](/images/cirray-chat-ppt/slide_01.png)

![第 2 张 — 痛点：国内触达困难](/images/cirray-chat-ppt/slide_02.png)

![第 3 张 — 解法](/images/cirray-chat-ppt/slide_03.png)

![第 4 张 — 产品对比：医疗咨询](/images/cirray-chat-ppt/slide_04.png)

![第 5 张 — 产品对比：建筑 CAD](/images/cirray-chat-ppt/slide_05.png)

![第 6 张 — 产品对比：荐股](/images/cirray-chat-ppt/slide_06.png)

![第 7 张 — 核心价值](/images/cirray-chat-ppt/slide_07.png)

![第 8 张 — 产品进度](/images/cirray-chat-ppt/slide_08.png)

![第 9 张 — 扫码体验](/images/cirray-chat-ppt/slide_09.png)

![第 10 张 — 下一步规划](/images/cirray-chat-ppt/slide_10.png)

![第 11 张 — 团队](/images/cirray-chat-ppt/slide_11.png)

![第 12 张 — 致谢](/images/cirray-chat-ppt/slide_12.png)

---

整套用 HTML 写的好处是排版完全自由，`clamp()` 字体自适应屏幕，Iconify 图标随手引用，Neumorphic 双层阴影一行 CSS 搞定。需要发 pptx 文件的时候，Playwright 批量截图，python-pptx 贴图打包，不依赖任何 PPT 软件。
