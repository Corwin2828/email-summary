# Azure 显示「没有访问权限」怎么办？

个人 Outlook（@outlook.com）的 IMAP **必须用 OAuth**，而 OAuth 需要 **Client ID**。Client ID 来自 Azure/Entra 的应用注册。

---

## 提示：「在目录外部创建应用程序的功能已被弃用」

自 **2024 年 6 月** 起，微软不再允许个人账号「无目录」注册应用。你必须先有一个 **目录（Tenant）**，常见获取方式：

| 方式 | 说明 | 难度 |
|------|------|------|
| **Azure 免费注册** | 最常见，可能需手机号；部分流程会创建 Default Directory | 中 |
| **M365 开发人员计划** | https://developer.microsoft.com/microsoft-365/dev-program | 中（有人不符合资格） |
| **改用 Gmail 汇总** | 不用 Azure，见文末「方法 C」 | **低（推荐备选）** |

### 路径 A：Azure 免费注册（拿到 Default Directory）

1. 用 **corwincc@outlook.com** 打开 https://azure.microsoft.com/free/
2. 点 **免费开始使用** → 登录个人 Outlook
3. 填写基本信息（国家、手机号验证等）
4. **关键**：若出现绑卡页面但不想绑卡，有用户反馈仅完成前几步（验证码 + 勾选协议 + 点「下一步」）等待数分钟后，右上角 **切换目录** 会出现 **Default Directory**
5. 切换目录后，打开：https://entra.microsoft.com/#view/Microsoft_AAD_RegisteredApps/CreateApplicationBlade
6. 创建应用时 **支持的账户类型** 务必选：
   - **「任何组织目录中的账户和个人 Microsoft 账户」**（英文：Multitenant + personal accounts）
   - 这样 OAuth 才能登录你的 @outlook.com 邮箱
7. 复制 Client ID → `.env` 的 `AZURE_CLIENT_ID`
8. **身份验证 → 允许公共客户端流 → 是**

### 路径 B：M365 开发人员计划

1. 打开 https://developer.microsoft.com/microsoft-365/dev-program
2. 用个人 Outlook 加入（需同意条款，部分账号可能提示不符合资格）
3. 成功后会有开发者租户，在 Entra 里注册应用（账户类型同样选「含个人 Microsoft 账户」）

---

## 原因 1：登录了学校/公司账号（最常见）

你可能用 **学校邮箱** 登录了 Azure，而应用要注册在 **个人 Outlook 账号** 对应的目录里。

**处理：**

1. 打开 https://portal.azure.com  
2. 点右上角 **头像**  
3. 看 **「切换目录」** / **「Switch directory」**  
4. 若有 `xxx.onmicrosoft.com` 且类型为 **个人** / **Default Directory**，选它  
5. 若没有个人目录 → 做 **原因 2** 免费注册  

**注册应用时**：用 **corwincc@outlook.com** 登录 Azure，不要用学校账号。

---

## 原因 2：从未开通 Azure 免费账户

仅有 Outlook 邮箱 **不等于** 有 Azure 注册应用权限。需先 **0 元开通** 免费 Azure（不会自动扣费，用于创建默认目录）。

1. 打开 https://azure.microsoft.com/free/  
2. 用 **corwincc@outlook.com** 登录  
3. 按提示完成注册（可能需要手机号验证）  
4. 完成后再打开：https://entra.microsoft.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade  

> 推荐用 **Entra 管理中心**（entra.microsoft.com），有时比 portal.azure.com 对个人账号更友好。

---

## 原因 3：门户入口不对

直接打开 **应用注册** 创建页（登录后）：

- https://entra.microsoft.com/#view/Microsoft_AAD_RegisteredApps/CreateApplicationBlade  
- 或 https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/CreateApplicationBlade  

创建时：

| 字段 | 填写 |
|------|------|
| 名称 | Email Summary |
| 支持的账户类型 | **个人 Microsoft 账户 only** |
| 重定向 URI | **留空** |

创建后：

1. 复制 **应用程序(客户端) ID** → 填入 `.env` 的 `AZURE_CLIENT_ID`  
2. **身份验证** → **允许公共客户端流** → **是** → 保存  

---

## 方法 B：用命令行注册（不打开 Azure 网页）

若已安装 Homebrew，可在 Mac 终端执行：

```bash
brew install azure-cli
az login --use-device-code
# 浏览器用 corwincc@outlook.com 登录

az ad app create --display-name "EmailSummary" \
  --sign-in-audience AzureADandPersonalMicrosoftAccount \
  --public-client-redirect-uris "http://localhost"

# 记下输出的 appId，即 AZURE_CLIENT_ID
APP_ID=这里填上面的appId

az ad app update --id $APP_ID --enable-public-client true
```

把 `appId` 写入 `.env`：

```env
AZURE_CLIENT_ID=你的appId
```

然后：

```bash
cd "/Users/corwin/Desktop/E mail Summary"
source .venv/bin/activate
python -m src.outlook_auth
```

---

## 方法 C：改用 Gmail 汇总（**不用 Azure，最快跑通**）

若 Azure / M365 开发者计划都卡住，建议改邮件汇总方案：

```
Gmail / 学校邮箱  --转发-->  一个 Gmail  --IMAP+应用密码-->  本程序
```

1. 准备一个 Gmail，开启 [IMAP](https://mail.google.com) + [应用专用密码](https://myaccount.google.com/apppasswords)
2. 把 corwincc@outlook.com 和其他邮箱 **转发到该 Gmail**
3. 修改 `.env`：

```env
GMAIL_ENABLED=true
GMAIL_ADDRESS=你的@gmail.com
GMAIL_APP_PASSWORD=16位应用密码

OUTLOOK_ENABLED=false
OUTLOOK_USE_OAUTH=false
```

飞书 / 企业微信 Webhook **无需改动**。

---

## 实在无法注册 Azure？（旧标题保留）

## 当前进度对照

| 项目 | 状态 |
|------|------|
| DeepSeek | 已配置 |
| 飞书 / 企业微信 | 已配置 |
| Outlook 应用密码 | 不可用（微软限制） |
| Outlook OAuth | **缺 AZURE_CLIENT_ID**（需完成上面任一路径） |

完成 Azure 注册并运行 `python -m src.outlook_auth` 后，Outlook 才能连上。
