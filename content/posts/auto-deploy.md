+++
title = "用 Zola + GitHub + 阿里云 ECS 实现博客自动发布"
date = 2026-03-22
description = "折腾了一晚上，终于实现了 git push 之后博客自动更新。记录一下过程和踩过的坑。"
+++

## 想实现什么

写完文章，在本地跑一下 `git push`，博客自动更新。不用登录服务器，不用手动上传文件。

最终效果：

```
本地写文章 → zola build → git push → GitHub 通知 ECS → git pull → 博客自动更新
```

## 技术选择

- **Zola**：静态博客框架，本地构建
- **GitHub**：托管代码和构建产物
- **阿里云 ECS + Nginx**：服务器和 Web 服务
- **webhook**：监听 GitHub push 事件，自动触发 `git pull`

有一个关键决策：**本地 build，把 `public/` 一起推到 GitHub**，ECS 只负责 `git pull`，不需要在服务器上装 Zola。好处是部署链路更简单，出问题更容易排查。

## 本地准备

Zola 默认会在 `.gitignore` 里忽略 `public/`，先把这行删掉，让 `public/` 也纳入版本控制。

`.gitignore` 只保留：

```
.claude/
```

然后 `git add .` 的时候遇到第一个坑：

```
warning: adding embedded git repository: themes/serene
```

主题 `themes/serene` 里有自己的 `.git`，变成了嵌套仓库。如果不处理，ECS `git pull` 后 `themes/` 目录会是空的，网站直接挂掉。

解决方法很简单，把主题的 `.git` 删掉，让它变成普通文件：

```bash
rm -rf themes/serene/.git
```

之后正常提交推送即可。

## ECS 配置

SSH 登录 ECS，把仓库 clone 下来：

```bash
git clone https://github.com/你的用户名/myblog.git ~/projects/blog
```

Nginx 指向 `public/` 目录：

```nginx
server {
    listen 443 ssl;
    server_name blog.cirray.cn;
    # 证书配置...

    root /home/ubuntu/projects/blog/public;
    index index.html;

    location / {
        try_files $uri $uri/ =404;
    }

    # webhook 反向代理
    location /hooks/ {
        proxy_pass http://127.0.0.1:9000/hooks/;
        proxy_set_header Host $host;
    }
}
```

webhook 通过 Nginx 反向代理，不需要对外单独开放 9000 端口。

## 配置 webhook 自动拉取

安装 webhook：

```bash
sudo apt install webhook -y
```

创建拉取脚本 `~/projects/blog/pull.sh`：

```bash
#!/bin/bash
cd /home/ubuntu/projects/blog
git pull origin main
```

```bash
chmod +x ~/projects/blog/pull.sh
```

创建 webhook 配置 `/etc/webhook.conf`：

```json
[
  {
    "id": "deploy-blog",
    "execute-command": "/home/ubuntu/projects/blog/pull.sh",
    "command-working-directory": "/home/ubuntu/projects/blog"
  }
]
```

创建 systemd 服务 `/etc/systemd/system/webhook.service`：

```ini
[Unit]
Description=Webhook for blog deploy
After=network.target

[Service]
User=ubuntu
ExecStart=/usr/bin/webhook -hooks /etc/webhook.conf -port 9000 -verbose
Restart=always

[Install]
WantedBy=multi-user.target
```

注意 `User=ubuntu` 这一行非常关键，后面会说为什么。

```bash
sudo systemctl enable webhook
sudo systemctl start webhook
```

## GitHub 配置 Webhook

仓库 → Settings → Webhooks → Add webhook：

- Payload URL：`https://blog.cirray.cn/hooks/deploy-blog`
- Content type：`application/json`
- 触发事件：Just the push event

## 踩的坑

配完之后 push 了一篇新文章，网站没更新。开始排查，踩了三个坑。

**坑一：git 报 dubious ownership**

webhook 日志里看到：

```
fatal: detected dubious ownership in repository at '/home/ubuntu/projects/blog'
```

原因是 webhook 服务默认以 root 身份运行，但仓库目录属于 ubuntu 用户，git 出于安全拒绝操作。

解决：在 systemd 服务配置里加 `User=ubuntu`，让 webhook 以 ubuntu 身份运行。

**坑二：.git/ 权限变成 root**

加了 `User=ubuntu` 之后，新报错：

```
error: cannot open .git/FETCH_HEAD: Permission denied
```

原因是排查过程中手动跑过 `sudo pull.sh`，导致 `.git/` 里的文件变成 root 所有，ubuntu 用户读不了。

解决：

```bash
sudo chown -R ubuntu:ubuntu /home/ubuntu/projects/blog
```

**坑三：ECS 访问 GitHub HTTPS 不稳定**

权限问题解决后，又遇到：

```
GnuTLS recv error (-110): The TLS connection was non-properly terminated
```

ECS 访问 GitHub 的 HTTPS 连接经常被重置，时好时坏。

解决：换成 SSH 协议拉取，稳定很多。在 ECS 上生成 SSH key：

```bash
ssh-keygen -t ed25519 -C "ecs-blog-deploy" -f ~/.ssh/id_ed25519 -N ""
cat ~/.ssh/id_ed25519.pub
```

把公钥加到 GitHub（Settings → SSH and GPG keys），然后改 remote URL：

```bash
git remote set-url origin git@github.com:你的用户名/myblog.git
```

验证：

```bash
ssh -T git@github.com
# Hi xxx! You've successfully authenticated
```

## 最终发布流程

```bash
zola build
git add .
git commit -m "新文章：xxx"
git push
```

等几秒，博客自动更新。
