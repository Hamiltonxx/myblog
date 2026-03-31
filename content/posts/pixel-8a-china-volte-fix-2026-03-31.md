+++
title = "Pixel 8a 在国内插联通卡能上网却打不了电话？用这两个工具 5 分钟搞定"
description = "Google 默认屏蔽了国内运营商的 VoLTE 配置，但不用 Root，Shizuku + Pixel IMS 就能把通话能力找回来。"
date = 2026-03-31

[taxonomies]
categories = ["工具"]
tags = ["pixel", "android", "volte", "adb", "shizuku", "china-unicom"]

[extra]
lang = "zh"
toc = true
+++

今天折腾了半天把 Pixel 8a 在国内跑通了——有信号、能上网，就是打不了电话。根本原因是 Google 没给国内运营商做 VoLTE 适配，把相关开关直接藏起来了。最终通过 Shizuku + Pixel IMS 解决，全程不需要 Root。

---

## 开发者模式 & 时间不准

第一步是开启开发者模式：**设置 → 关于手机 → 版本号，连点 7 次**，搞定后在「系统 → 开发者选项」里找到 USB 调试并开启。

插上联通卡之后时间自动同步了（基站 NITZ 校准），这个倒不用单独处理。如果没卡的时候时间不准，可以用 ADB 把 NTP 服务器改成阿里云的：

```bash
adb shell settings put global ntp_server ntp.aliyun.com
```

---

## 为什么有信号却打不了电话

国内运营商已经基本关停了 2G/3G 网络，打电话必须走 VoLTE（通话走 4G/5G 数据通道）。Pixel 因为没有正式进入中国市场，固件里没有内置国内运营商的配置文件，系统识别到中国 SIM 卡时直接把 VoLTE 开关隐藏掉了。

进设置找不到「高清通话」或「VoLTE」开关，这就是原因。

---

## 解决方案：Shizuku + Pixel IMS

两个工具分工明确：

- **Shizuku**：利用 ADB 权限给其他 App 提供系统级授权，不需要 Root
- **Pixel IMS**（包名 `dev.bluehouse.enablevolte`）：通过 Shizuku 拿到权限后，强制写入 VoLTE 运营商配置

### 安装 APK

Mac 上有 Android Studio 的话，adb 已经在 `~/Library/Android/sdk/platform-tools/` 里了。直接用：

```bash
adb install shizuku.apk
adb install dev.bluehouse.enablevolte.apk
```

### 启动 Shizuku（Android 11+ 专用方式）

旧的脚本路径（`/sdcard/Android/data/...`）在 Android 14 上因为沙盒限制已经失效了。正确做法是在 Shizuku App 里点「通过连接电脑启动 → 查看指令」，它会给你一个专属路径：

```bash
adb shell /data/app/~~<随机hash>==/moe.shizuku.privileged.api-<hash>==/lib/arm64/libshizuku.so
```

这个路径每台设备不同，必须从 App 里复制，不能照搬别人的。跑完之后手机上 Shizuku 显示「正在运行」就好了。

### 开启 VoLTE

1. 打开 Pixel IMS，授予 Shizuku 权限（选「始终允许」）
2. 找到联通卡，把 **启用 VoLTE** 开关拨到 ON
3. 等几秒或重启手机

成功的标志：回到 Pixel IMS 主页，看到**「支持 VoLTE: 是，IMS 状态: 已注册」**，说明手机已经和联通 IMS 服务器握手成功。

---

## 验证

拨打 10010，通话时信号栏依然显示 4G/5G（没有掉到 E 或无服务）就代表 VoLTE 工作正常。

---

## 注意事项

**系统更新后可能需要重来一次**：每次 Android 大版本更新后，Google 可能会重置运营商配置。到时候再用 ADB 跑一下 Shizuku 启动命令，进 Pixel IMS 确认开关还是 ON，重启即可。

**不影响保修**：整个操作没有解锁 Bootloader，也没有 Root，不会触发 Google 的保修失效标志。
