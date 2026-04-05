+++
title = "把 Claude 送给我妈：用自己的 Pro 账号给家人做一个开箱即用的 App"
description = "国产 AI 乱说一气被我妈卸载，Claude 才是她需要的。但网络和支付把她挡在门外——我决定自己动手解决这个问题。"
date = 2026-04-05

[taxonomies]
categories = ["项目"]
tags = ["android", "webview", "cookie", "sing-box", "trojan", "aes-cbc"]

[extra]
lang = "zh"
toc = true
+++

我妈问了一个病理问题，豆包乱说一气，被她立马卸载了。

我知道如果她用的是 Claude，绝对不会这样。Claude Code 是我用过的最强 Agent，没有之一。它回答问题的质量、态度、边界感，都是我见过最让人满意的。我非常想把它推荐给我的家人，甚至农村里的朋友。

但现实是：Claude 在国内访问不了，注册要境外手机号，付款要境外信用卡。这三道门，把我妈、我的朋友，还有无数普通人，全挡在外面。他们最多只能接触"豆包"这种国产垃圾 App。

所以我突发奇想：**用我自己的 Pro 账号，把登录状态克隆进一个 Android App，打包给她装上，打开就能用。** 不需要注册，不需要翻墙，不需要懂任何东西。

今天把这件事做成了。

![最终效果：Pixel 8a 上运行的 Claude，已登录我的 Pro 账号](/images/claude-android-2026-04-05.png)

打开即是 "Back at it, Cirray"，Sonnet 4.6 完整可用。

---

## 整体思路

1. 从 Mac 的 Chrome 里提取 claude.ai 的 Cookie / Session
2. 打包成 Android WebView App，启动时自动注入 Cookie
3. App 内置 sing-box + Trojan 代理，自动翻墙
4. 发给家人安装，打开即用

---

## Cookie 提取：破解 Chrome 的加密

Chrome 的 Cookie 存在 SQLite 里：

```
~/Library/Application Support/Google/Chrome/Default/Cookies
```

所有值都是加密的，`value` 字段为空，真正的内容在 `encrypted_value` 里。

### 密钥从哪来

macOS Chrome 把加密密钥存在系统 Keychain，用 `security` 命令取出来：

```python
result = subprocess.run(
    ["security", "find-generic-password", "-w",
     "-a", "Chrome", "-s", "Chrome Safe Storage"],
    capture_output=True, text=True
)
password = result.stdout.strip()
```

然后 PBKDF2 派生 16 字节 AES 密钥：

```python
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

kdf = PBKDF2HMAC(algorithm=hashes.SHA1(), length=16,
                 salt=b"saltysalt", iterations=1003)
key = kdf.derive(password.encode("utf8"))
```

### 加密格式：网上资料是错的

网上普遍说格式是：

```
v10 + AES-CBC(key, IV=" "*16, plaintext)
```

按这个写完，解密出来前面一堆乱码。调试后发现**实际格式是**：

```
v10（3字节） + 明文IV（16字节） + AES-CBC密文
```

而且密文解密后，**第一个 AES 块（16字节）是随机 nonce，要跳过**，剩下的才是真正的 Cookie 值：

```python
def decrypt_cookie(encrypted_value, key):
    payload = encrypted_value[3:]      # 去掉 v10 前缀
    iv = payload[:16]                  # 真实 IV（明文存储）
    ciphertext = payload[16:]          # 真实密文

    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    decrypted = (cipher.decryptor().update(ciphertext)
                 + cipher.decryptor().finalize())

    padding = decrypted[-1]
    raw = decrypted[16:-padding]       # 跳过第一个 16 字节随机 nonce
    return raw.decode('utf-8', errors='replace')
```

跑完拿到 35 条 claude.ai 的 Cookie，包括 `sessionKey`、`routingHint`、`anthropic-device-id` 等关键字段。

---

## Android 端：注入 Cookie

把提取的 Cookie JSON 放进 `assets/cookies.json`，App 启动时用 `CookieManager` 注入：

```kotlin
val cookieManager = CookieManager.getInstance()
for (cookie in cookies) {
    cookieManager.setCookie("https://${domain}", buildCookieString(cookie))
}
cookieManager.flush()
webView.loadUrl("https://claude.ai")
```

Cookie 里的 expires 是 Chrome 时间戳（微秒，从 1601-01-01 起算），转 Unix 时间要减偏移：

```kotlin
val unixMillis = (cookie.expires / 1000) - 11644473600000L
```

---

## 内置代理：sing-box + Trojan

claude.ai 国内不通，所以 App 里内置了 sing-box，启动时在本地跑一个 HTTP 代理（127.0.0.1:10809），WebView 流量全走 Trojan 节点出去。

WebView 走代理用 `androidx.webkit.ProxyController`（Android 10+）：

```kotlin
ProxyController.getInstance().setProxyOverride(
    ProxyConfig.Builder().addProxyRule("127.0.0.1:10809").build(),
    Executors.newSingleThreadExecutor()
) { loadPage() }
```

### 坑1：filesDir 不可执行

把 sing-box 二进制复制到 `filesDir` 再执行，直接失败。Android 的 `filesDir` 挂载了 `noexec`，不允许执行任何程序。

解决：把 sing-box 改名为 `libsingbox.so`，放进 `jniLibs/arm64-v8a/`。Android 会把它安装到 `nativeLibraryDir`，这个目录可以执行：

```kotlin
val binary = File(context.applicationInfo.nativeLibraryDir, "libsingbox.so")
binary.setExecutable(true)
```

### 坑2：.so 被 APK 压缩

`jniLibs` 里的文件默认会被压缩，安装后文件不完整导致无法运行。在 `build.gradle` 里关掉：

```groovy
packagingOptions {
    doNotStrip "**/*.so"
    jniLibs {
        useLegacyPackaging true
    }
}
```

---

## 局限性

Cookie 有过期时间。Cloudflare 相关的 token 几小时就失效，`sessionKey` 相对长效。失效了我在 Mac 上重新跑一次提取脚本，重新 build 发给她就行——对我来说不麻烦，对她来说完全无感。

---

豆包让我妈失望的那一刻，我就在想这件事。今天终于做完了。

技术从来不是目的，能让她用上一个真正靠谱的工具，才是。
