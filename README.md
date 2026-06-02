# 邮件总结助手

在 Mac 或 Linux VPS 上监听邮箱新邮件，用 [DeepSeek](https://platform.deepseek.com/) 生成中文总结，并推送到 **飞书** 或 **企业微信** 群机器人。默认由 AI 判断是否值得总结，并自动生成推送全文。

适合：多个邮箱（Gmail / Outlook / 学校邮箱）汇总到一处、不想被验证码和营销邮件刷屏、希望用飞书/企微收「可读摘要」的场景。

---

## 功能概览

- **IMAP 轮询**监听 Gmail / Outlook（个人 Outlook 需 OAuth）
- **AI 过滤**（`FILTER_MODE=ai`）：验证码、营销、订阅等由 DeepSeek 判断是否跳过
- **AI 推送格式**（`NOTIFY_FORMAT=ai`）：DeepSeek 按 Prompt 生成整段飞书/企微消息（区分发件人与「转发自哪个邮箱」）
- **关闭期间补发**：正常 `Ctrl+C` 退出后，下次启动可总结上次关闭以来收到的邮件
- **本地网页配置**：`./settings.sh` 修改 API、Webhook、Prompt
- **Mac 双击启动**：`启动邮件助手.command` / `打开设置.command`

> **说明**：本工具**不能**推送到个人微信；请使用飞书或企业微信群机器人。

---

## 你需要准备什么

| 项目 | 是否必须 | 说明 |
|------|----------|------|
| [DeepSeek API Key](https://platform.deepseek.com/api_keys) | 是 | 用于过滤与总结 |
| Gmail + 应用专用密码 | 推荐 | 最省事的监听方式；也可只监听 Outlook |
| 飞书 **或** 企业微信 Webhook | 至少一个 | 用于接收推送 |
| Outlook OAuth（Azure Client ID） | 仅直连 Outlook 时 | 个人 @outlook.com 已不能用应用密码登录 IMAP |

**多邮箱建议架构**（学校邮箱 / 个人 Outlook 转发不稳时）：

```text
学校邮箱、个人 Outlook  ──自动转发──►  一个 Gmail（汇总）
                                              │
                                         IMAP 监听
                                              ▼
                                        本程序 ──► 飞书 / 企微
```

---

## 快速开始

### 1. 克隆与安装

```bash
git clone https://github.com/你的用户名/email-summary.git
cd email-summary

cp .env.example .env
# 按下面章节填写 .env

chmod +x run.sh settings.sh 启动邮件助手.command 打开设置.command
./run.sh
```

首次运行会自动创建 `.venv` 并安装依赖。终端出现 **`邮件总结助手已运行`** 即表示成功。

### 2. Mac 用户（可选）

- 双击 **`启动邮件助手.command`** 运行
- 双击 **`打开设置.command`** 打开配置页
- 首次若提示「无法打开」：**右键 → 打开** 确认一次

### 3. 网页配置（可选）

```bash
./settings.sh
```

浏览器访问 **http://127.0.0.1:8765/** ，保存后**重启** `./run.sh`。

---

## 一、获取 DeepSeek API Key

1. 打开 [DeepSeek 开放平台](https://platform.deepseek.com/)
2. 注册 / 登录 → **API Keys** → **创建 API Key**
3. 复制 Key（形如 `sk-...`），填入 `.env`：

```env
DEEPSEEK_API_KEY=sk-xxxxxxxx
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
```

> 邮件正文会发送到 DeepSeek 接口处理，请勿将 Key 提交到 GitHub。

---

## 二、配置 Gmail IMAP（推荐）

本程序通过 **IMAP** 读取邮箱，不是登录网页。Gmail 需要使用 **应用专用密码**（不是 Google 账号的普通密码）。

### 2.1 开启 IMAP

1. 打开 [Gmail](https://mail.google.com/) → 右上角 **设置** ⚙ → **查看所有设置**
2. 标签页 **转发和 POP/IMAP** → **IMAP 访问** 选 **启用 IMAP**
3. 保存

（2024 年起多数个人 Gmail 默认已开启 IMAP，若界面无此项可跳过。）

### 2.2 开启两步验证

1. 打开 [Google 账号安全](https://myaccount.google.com/security)
2. **两步验证** → 按提示开启（可用 Authenticator，不必绑手机）

### 2.3 创建应用专用密码

1. 打开 [应用专用密码](https://myaccount.google.com/apppasswords)（需已开启两步验证）
2. 应用名称随意（如 `EmailSummary`）→ **创建**
3. 复制 **16 位密码**（形如 `abcd efgh ijkl mnop`，填入 `.env` 时可去掉空格）

### 2.4 写入 `.env`

```env
GMAIL_ENABLED=true
GMAIL_ADDRESS=你的邮箱@gmail.com
GMAIL_APP_PASSWORD=abcdefghijklmnop
```

### 2.5 把其他邮箱转发到该 Gmail（可选）

- **学校 Outlook**：网页版 Outlook → **设置 → 邮件 → 转发** → 填 Gmail 地址  
- **个人 Outlook**：同上；若转发被微软自动关闭，见 [常见问题](#常见问题)

转发后，程序仍只连 Gmail，由 DeepSeek 从邮件头/正文判断「转发自哪个邮箱」。

可选别名（方便推送里显示）：

```env
FORWARD_SOURCE_MAP=you@school.edu:学校邮箱,you@outlook.com:个人Outlook
```

---

## 三、获取飞书 Webhook

飞书 **自定义机器人** 需在 **桌面端或网页版** 创建（手机 App 里往往没有入口）。

### 3.1 创建步骤

1. 打开 [飞书](https://www.feishu.cn/) 客户端或网页版  
2. 进入要接收总结的 **群聊**（可自建群）  
3. 群名称旁 **⋯** → **设置** → **群机器人**（或 **机器人**）  
4. **添加机器人** → **自定义机器人**（Custom Bot）  
5. 设置名称（如「邮件总结」）→ 安全设置可选「自定义关键词」（若开启，邮件内容需含该词，**建议先不开启**）  
6. 复制 **Webhook 地址**，形如：

```text
https://open.feishu.cn/open-apis/bot/v2/hook/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

### 3.2 写入 `.env`

```env
FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/你的token
```

### 3.3 自测

```bash
curl -X POST "$FEISHU_WEBHOOK_URL" \
  -H "Content-Type: application/json" \
  -d '{"msg_type":"text","content":{"text":"邮件助手连接测试"}}'
```

群内收到消息即成功。

---

## 四、获取企业微信 Webhook

需使用 **企业微信**（不是个人微信）。没有企业可先 [注册企业微信](https://work.weixin.qq.com/)（可免费创建团队）。

### 4.1 创建步骤

1. 打开 **企业微信** 桌面端或 [管理后台](https://work.weixin.qq.com/)  
2. 进入一个 **内部群聊**（需先创建群）  
3. 群聊右上角 **⋯** → **群机器人**（部分版本在 **添加群机器人** / **消息推送**）  
4. **添加** → 设置机器人名称  
5. 复制 **Webhook 地址**，形如：

```text
https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

### 4.2 写入 `.env`

```env
WECOM_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=你的key
```

飞书与企微**可同时填写**，每封总结会推送到两个渠道。

> **个人微信**无官方稳定 Webhook，本仓库不支持直连个人微信。

---

## 五、配置 Outlook IMAP（可选）

| 账号类型 | 登录方式 |
|----------|----------|
| 个人 `@outlook.com` / `@hotmail.com` | **必须 OAuth**（应用密码已失效） |
| 学校 / 公司 Microsoft 365 | 常需管理员放行；更简单是 **转发到 Gmail** |

### 5.1 开启 IMAP（个人 Outlook）

1. 打开 [Outlook 网页版](https://outlook.live.com/)  
2. **设置** → **邮件** → **转发和 IMAP** → 开启 **IMAP**

### 5.2 OAuth 配置（个人账号）

微软要求注册 Azure 应用获取 `AZURE_CLIENT_ID`，并在本机/VPS 完成一次浏览器登录。

详细步骤（含「没有 Azure 权限」）：见 **[docs/Azure注册与无权限解决.md](docs/Azure注册与无权限解决.md)**。

`.env` 示例：

```env
OUTLOOK_ENABLED=true
OUTLOOK_ADDRESS=you@outlook.com
OUTLOOK_USE_OAUTH=true
AZURE_CLIENT_ID=你的-client-id
```

首次登录：

```bash
source .venv/bin/activate
python -m src.outlook_auth
```

Token 保存在 `data/outlook_msal_cache.json`（已在 `.gitignore` 中忽略，勿上传 GitHub）。

---

## 配置说明（`.env`）

完整模板见 [.env.example](.env.example)。

| 变量 | 说明 | 默认 |
|------|------|------|
| `FILTER_MODE` | `ai` = DeepSeek 判断是否总结；`rules` = 本地规则 | `ai` |
| `NOTIFY_FORMAT` | `ai` = DeepSeek 生成推送全文；`template` = 本地模板 | `ai` |
| `DAILY_DIGEST_ENABLED` | 每日简报开关（预留配置） | `false` |
| `DAILY_DIGEST_TIME` | 每日简报时间（`HH:MM`，24 小时制） | `21:30` |
| `CATCHUP_SINCE_LAST_RUN` | 启动时补发上次退出后的邮件 | `true` |
| `PROCESS_EXISTING_UNREAD` | 启动时处理全部未读（慎用） | `false` |
| `IMAP_USE_IDLE` | IMAP IDLE（易断线，不推荐） | `false` |
| `POLL_INTERVAL_SEC` | 检查新邮件间隔（秒，`1800`=30 分钟） | `1800` |
| `IMAP_OVERQUOTA_WAIT_SEC` | Gmail `OVERQUOTA` 限流后等待再重试（秒） | `10800`（3 小时） |
| `MAX_BODY_CHARS` | 送入模型的最大正文字符 | `12000` |
| `WEB_HOST` / `WEB_PORT` | 配置页监听地址 | `127.0.0.1` / `8765` |

自定义总结/过滤逻辑：编辑 `data/prompts.json`，或在设置页修改 **推送 Prompt** / **过滤 Prompt**。

---

## 部署到云服务器（推荐新加坡节点）

程序资源占用低，**1 核 1GB** 即可。

| 推荐 | 说明 |
|------|------|
| 腾讯云 / 阿里云 **新加坡轻量** 2核2G | 成本通常低于香港，适合本项目 |
| 腾讯云 / 阿里云 香港轻量 2核2G | 线路更近大陆，但价格偏高 |
| Vultr 新加坡 / 香港 | 按量月付 |

```bash
# 服务器上（Ubuntu 22.04+）
sudo apt update && sudo apt upgrade -y
sudo apt install -y git python3 python3-venv python3-pip

cd /opt
sudo git clone https://github.com/你的用户名/email-summary.git
sudo chown -R $USER:$USER /opt/email-summary
cd /opt/email-summary

cp .env.example .env && nano .env   # 填入密钥，勿泄露
chmod 600 .env

chmod +x run.sh
./run.sh   # 首次试跑成功后 Ctrl+C

# 配置 systemd 常驻
sudo cp scripts/email-summary.service /etc/systemd/system/email-summary.service
sudo nano /etc/systemd/system/email-summary.service
# 推荐修改为：
# User=ubuntu
# WorkingDirectory=/opt/email-summary
# ExecStart=/opt/email-summary/.venv/bin/python -m src.main

sudo systemctl daemon-reload
sudo systemctl enable --now email-summary
sudo systemctl status email-summary
sudo journalctl -u email-summary -f
```

- **不要**将配置页 `8765` 端口直接对公网开放；远程改配置建议用 SSH 隧道：`ssh -L 8765:127.0.0.1:8765 user@服务器IP`
- 确保 VPS 能访问：`imap.gmail.com:993`、`api.deepseek.com`、飞书/企微 API
- 腾讯云安全组建议：
  - 必开：`22/tcp`（SSH）
  - 如使用方案B：再开 `80/tcp`（以及后续 `443/tcp`）
  - 不建议直接开放 `8765/tcp`

### 方案B：直接浏览器访问配置页（Nginx + 账号密码）

如果你希望不用 SSH 隧道，直接在浏览器打开 `https://你的域名/settings`，推荐用 Nginx 反向代理 + 基础认证：

1. 准备一个域名并解析到 VPS 公网 IP
2. 安装 Nginx 与密码工具

```bash
sudo apt install -y nginx apache2-utils
sudo htpasswd -c /etc/nginx/.htpasswd admin
```

3. 新建 Nginx 配置（将 `your.domain.com` 改为你的域名）

```nginx
server {
    listen 80;
    server_name your.domain.com;

    location /settings/ {
        proxy_pass http://127.0.0.1:8765/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        auth_basic "Email Summary Settings";
        auth_basic_user_file /etc/nginx/.htpasswd;
    }
}
```

4. 启用配置并重载 Nginx

```bash
sudo nginx -t
sudo systemctl reload nginx
```

5. 单独启动设置页服务（建议另建 systemd，避免手工运行）

```bash
cd /opt/email-summary
./settings.sh
```

> 强烈建议继续加 HTTPS（Let's Encrypt）后再长期开放公网访问；否则账号密码会明文传输。


---

## 常见问题

### 飞书收不到消息

- Webhook 是否完整复制（含 `hook/` 后整段）
- 机器人是否开启了「关键词」安全策略（可先关闭）
- 用上文 `curl` 命令单独测试 Webhook

### Gmail 报 `OVERQUOTA` / bandwidth limits

- 表示 Gmail **暂时限制 IMAP**（连接太多、拉信太猛等），程序会自动等待后重试
- 默认限流后 **3 小时** 再连（`IMAP_OVERQUOTA_WAIT_SEC=10800`），避免频繁重试加重封禁
- 请关闭重复的「邮件助手」窗口、手机邮件客户端等同账号 IMAP，等待 1～24 小时后再试

### Gmail 登录失败 `AUTHENTICATE failed`

- 必须使用 **应用专用密码**，不是 Google 登录密码
- 确认已开启 **两步验证**
- 大陆网络可尝试 VPS 或代理；Gmail IMAP 为 `imap.gmail.com:993`

### Outlook 转发自动关闭

- 微软会将「转发到外部邮箱」视为高风险并关闭，属平台策略，非本程序导致
- 建议：完成 **Outlook OAuth** 让程序直连；或仅依赖 **学校邮箱 → Gmail** 转发

### 学校邮箱无法转发到 Gmail

- 学校 IT 可能禁止 **外部自动转发**，需联系管理员或使用 OAuth（见 Azure 文档）

### 程序关了期间的邮件会丢吗

- 默认 `CATCHUP_SINCE_LAST_RUN=true`，用 **Ctrl+C** 正常退出会记录时间，下次启动会补发（每轮有上限，陆续推送）

### 修改配置不生效

- 网页或 `.env` 修改后需 **重启** `./run.sh` 或 `systemctl restart email-summary`

---

## 隐私与安全

- 邮件正文会发送至 **DeepSeek API** 生成总结
- `.env`、`data/outlook_msal_cache.json`、`data/processed.db` 含敏感信息，**勿提交 Git**
- VPS 上建议：`chmod 600 .env`

---

## 目录结构

```text
├── .env.example           # 配置模板（提交到 Git）
├── run.sh                 # 启动监听
├── settings.sh            # 启动配置网页
├── 启动邮件助手.command    # macOS 双击运行
├── 打开设置.command
├── requirements.txt
├── scripts/
│   └── email-summary.service   # Linux systemd 示例
├── docs/
│   └── Azure注册与无权限解决.md
├── web/                   # 配置页前端
└── src/
    ├── main.py
    ├── imap_watcher.py
    ├── deepseek_client.py
    ├── notify.py
    └── ...
```

---

## 相关文档

- [Outlook OAuth / Azure 注册问题解决](docs/Azure注册与无权限解决.md)

---

## License

请根据你的需要自行添加 `LICENSE` 文件（如 MIT）。未包含 License 时，他人默认保留所有权利。
