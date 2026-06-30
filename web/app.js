const SECRET_KEYS = new Set([
  "DEEPSEEK_API_KEY",
  "BUSINESS_DEEPSEEK_API_KEY",
  "GMAIL_APP_PASSWORD",
  "OUTLOOK_APP_PASSWORD",
  "BUSINESS_EMAIL_PASSWORD",
  "FEISHU_WEBHOOK_URL",
  "WECOM_WEBHOOK_URL",
  "BUSINESS_FEISHU_WEBHOOK_URL",
  "BUSINESS_WECOM_WEBHOOK_URL",
]);

const BOOL_KEYS = new Set([
  "GMAIL_ENABLED",
  "OUTLOOK_ENABLED",
  "OUTLOOK_USE_OAUTH",
  "BUSINESS_EMAIL_ENABLED",
  "BUSINESS_QUIET_HOURS_ENABLED",
  "BUSINESS_PROCESS_EXISTING_UNREAD",
  "BUSINESS_BYPASS_FILTER",
  "IMAP_USE_IDLE",
  "HEARTBEAT_ALERT_ENABLED",
  "DAILY_DIGEST_ENABLED",
  "PROCESS_EXISTING_UNREAD",
  "CATCHUP_SINCE_LAST_RUN",
]);

const FIELD_GROUPS = [
  {
    title: "AEBBS 企业邮箱账号",
    description: "这里控制 AEBBS 业务邮箱登录和独立通知渠道。",
    fields: [
      "BUSINESS_EMAIL_ENABLED",
      "BUSINESS_EMAIL_NAME",
      "BUSINESS_EMAIL_ADDRESS",
      "BUSINESS_EMAIL_IMAP_HOST",
      "BUSINESS_EMAIL_IMAP_PORT",
      "BUSINESS_EMAIL_PASSWORD",
      "BUSINESS_FEISHU_WEBHOOK_URL",
      "BUSINESS_WECOM_WEBHOOK_URL",
      "BUSINESS_KNOWLEDGE_DIR",
    ],
  },
  {
    title: "AEBBS AI 模型",
    description: "客户询盘要求快速响应；基础设置用 Flash，靠保守过滤提示词防漏。",
    fields: [
      "BUSINESS_DEEPSEEK_API_KEY",
      "BUSINESS_DEEPSEEK_BASE_URL",
      "BUSINESS_DEEPSEEK_MODEL",
    ],
  },
  {
    title: "AEBBS 运行设置",
    description: "企业邮箱按更快频率监听；这些设置只影响 AEBBS，不影响个人邮箱。",
    fields: [
      "BUSINESS_POLL_INTERVAL_SEC",
      "BUSINESS_IMAP_RETRY_WAIT_SEC",
      "BUSINESS_RETRY_FAILED_AFTER_SEC",
      "BUSINESS_PROCESS_EXISTING_UNREAD",
      "BUSINESS_BYPASS_FILTER",
      "BUSINESS_QUIET_HOURS_ENABLED",
    ],
  },
  {
    title: "个人邮箱账号",
    description: "这里控制个人 Gmail / Outlook 登录和个人通知渠道。",
    fields: [
      "GMAIL_ENABLED",
      "GMAIL_ADDRESS",
      "GMAIL_APP_PASSWORD",
      "OUTLOOK_ENABLED",
      "OUTLOOK_ADDRESS",
      "OUTLOOK_USE_OAUTH",
      "AZURE_CLIENT_ID",
      "OUTLOOK_APP_PASSWORD",
      "FEISHU_WEBHOOK_URL",
      "WECOM_WEBHOOK_URL",
    ],
  },
  {
    title: "个人邮箱 AI 模型",
    description: "个人邮件优先省钱和稳定，默认使用 DeepSeek Flash。",
    fields: [
      "DEEPSEEK_API_KEY",
      "DEEPSEEK_BASE_URL",
      "DEEPSEEK_MODEL",
    ],
  },
  {
    title: "个人邮箱运行设置",
    description: "这些设置只影响个人 Gmail / Outlook；建议一小时轮询一次。",
    fields: [
      "IMAP_USE_IDLE",
      "POLL_INTERVAL_SEC",
      "IMAP_OVERQUOTA_WAIT_SEC",
      "PROCESS_EXISTING_UNREAD",
      "CATCHUP_SINCE_LAST_RUN",
    ],
  },
  {
    title: "系统与网页后台",
    description: "这里控制程序告警、AI 输入长度、通知格式和网页后台监听方式。",
    fields: [
      "HEARTBEAT_ALERT_ENABLED",
      "HEARTBEAT_STALL_SEC",
      "HEARTBEAT_CHECK_SEC",
      "DATA_DIR",
      "MAX_BODY_CHARS",
      "FILTER_MODE",
      "NOTIFY_FORMAT",
      "DAILY_DIGEST_ENABLED",
      "DAILY_DIGEST_TIME",
      "WEB_HOST",
      "WEB_PORT",
    ],
  },
];

const FIELD_LABELS = {
  BUSINESS_EMAIL_ENABLED: "启用 AEBBS 企业邮箱",
  BUSINESS_EMAIL_NAME: "AEBBS 邮箱显示名",
  BUSINESS_EMAIL_ADDRESS: "AEBBS 邮箱地址",
  BUSINESS_EMAIL_IMAP_HOST: "AEBBS IMAP 主机",
  BUSINESS_EMAIL_IMAP_PORT: "AEBBS IMAP 端口",
  BUSINESS_EMAIL_PASSWORD: "AEBBS 邮箱密码",
  BUSINESS_POLL_INTERVAL_SEC: "AEBBS 轮询间隔（秒，建议 60）",
  BUSINESS_IMAP_RETRY_WAIT_SEC: "AEBBS IMAP 失败重试（秒）",
  BUSINESS_RETRY_FAILED_AFTER_SEC: "AEBBS 失败邮件重试等待（秒）",
  BUSINESS_PROCESS_EXISTING_UNREAD: "处理 AEBBS 现有未读邮件",
  BUSINESS_BYPASS_FILTER: "AEBBS 跳过 AI 过滤",
  BUSINESS_QUIET_HOURS_ENABLED: "启用 AEBBS 静默时段",
  BUSINESS_FEISHU_WEBHOOK_URL: "AEBBS 飞书 Webhook",
  BUSINESS_WECOM_WEBHOOK_URL: "AEBBS 企业微信 Webhook",
  BUSINESS_DEEPSEEK_API_KEY: "AEBBS DeepSeek API Key",
  BUSINESS_DEEPSEEK_BASE_URL: "AEBBS DeepSeek Base URL",
  BUSINESS_DEEPSEEK_MODEL: "AEBBS DeepSeek 模型",
  BUSINESS_KNOWLEDGE_DIR: "AEBBS 知识库目录",
  DEEPSEEK_API_KEY: "个人邮箱 DeepSeek API Key",
  DEEPSEEK_BASE_URL: "个人邮箱 DeepSeek Base URL",
  DEEPSEEK_MODEL: "个人邮箱 DeepSeek 模型",
  GMAIL_ENABLED: "启用 Gmail",
  GMAIL_ADDRESS: "Gmail 地址",
  GMAIL_APP_PASSWORD: "Gmail 应用专用密码",
  OUTLOOK_ENABLED: "启用 Outlook",
  OUTLOOK_ADDRESS: "Outlook 地址",
  OUTLOOK_USE_OAUTH: "Outlook 使用 OAuth",
  AZURE_CLIENT_ID: "Azure Client ID",
  OUTLOOK_APP_PASSWORD: "Outlook 应用密码",
  FEISHU_WEBHOOK_URL: "个人飞书 Webhook",
  WECOM_WEBHOOK_URL: "个人企业微信 Webhook",
  IMAP_USE_IDLE: "使用 IMAP IDLE",
  POLL_INTERVAL_SEC: "个人邮箱轮询间隔（秒，建议 3600）",
  IMAP_OVERQUOTA_WAIT_SEC: "Gmail 限流等待（秒）",
  HEARTBEAT_ALERT_ENABLED: "启用卡住告警",
  HEARTBEAT_STALL_SEC: "卡住判定秒数",
  HEARTBEAT_CHECK_SEC: "心跳检查间隔（秒）",
  DATA_DIR: "数据目录",
  MAX_BODY_CHARS: "AI 读取正文上限",
  FILTER_MODE: "过滤模式",
  NOTIFY_FORMAT: "通知格式",
  DAILY_DIGEST_ENABLED: "启用每日汇总",
  DAILY_DIGEST_TIME: "每日汇总时间",
  PROCESS_EXISTING_UNREAD: "处理个人邮箱现有未读邮件",
  CATCHUP_SINCE_LAST_RUN: "下次启动补处理",
  WEB_HOST: "网页监听地址",
  WEB_PORT: "网页监听端口",
};

const FIELD_PLACEHOLDERS = {
  DEEPSEEK_BASE_URL: "https://api.deepseek.com",
  BUSINESS_DEEPSEEK_BASE_URL: "https://api.deepseek.com",
  DEEPSEEK_MODEL: "deepseek-v4-flash",
  BUSINESS_DEEPSEEK_MODEL: "deepseek-v4-flash",
  POLL_INTERVAL_SEC: "3600",
  BUSINESS_POLL_INTERVAL_SEC: "60",
  BUSINESS_IMAP_RETRY_WAIT_SEC: "300",
  BUSINESS_RETRY_FAILED_AFTER_SEC: "120",
};

const FIELD_OPTIONS = {
  FILTER_MODE: [
    ["ai", "AI 判断是否推送"],
    ["rules", "本地规则过滤"],
  ],
  NOTIFY_FORMAT: [
    ["ai", "AI 生成完整通知"],
    ["template", "本地模板通知"],
  ],
};

const WIDE_FIELD_KEYS = new Set([
  "DEEPSEEK_API_KEY",
  "BUSINESS_DEEPSEEK_API_KEY",
  "DEEPSEEK_BASE_URL",
  "BUSINESS_DEEPSEEK_BASE_URL",
  "GMAIL_APP_PASSWORD",
  "OUTLOOK_APP_PASSWORD",
  "AZURE_CLIENT_ID",
  "BUSINESS_EMAIL_PASSWORD",
  "FEISHU_WEBHOOK_URL",
  "WECOM_WEBHOOK_URL",
  "BUSINESS_FEISHU_WEBHOOK_URL",
  "BUSINESS_WECOM_WEBHOOK_URL",
  "BUSINESS_KNOWLEDGE_DIR",
  "DATA_DIR",
]);

const ROLE_LABELS = {
  owner: "管理员",
  team: "团队账号",
};

const ERROR_MESSAGES = {
  unauthorized: "请先登录。",
  forbidden: "当前账号没有权限操作这一项。",
  "bad csrf": "登录状态已变化，请刷新页面后重新登录。",
  "too many attempts": "登录失败次数过多，请等几分钟后再试。",
  "invalid login": "账号或密码不正确。",
  "Request failed": "请求失败，请稍后再试。",
};

let csrfToken = "";
let currentUser = null;
let settingsSnapshot = null;

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

function toast(message, ok = true) {
  const el = $("#toast");
  el.textContent = message;
  el.className = `toast ${ok ? "ok" : "error"}`;
  el.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => {
    el.hidden = true;
  }, 4200);
}

function translateError(message) {
  return ERROR_MESSAGES[message] || message;
}

async function api(path, options = {}) {
  const headers = {
    ...(options.headers || {}),
  };
  if (options.body && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  if (csrfToken && options.method && options.method !== "GET") {
    headers["X-CSRF-Token"] = csrfToken;
  }
  const res = await fetch(path, { ...options, headers });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.ok === false) {
    const message = data.error || (data.errors || ["Request failed"]).join("; ");
    throw new Error(translateError(message));
  }
  return data;
}

function showLogin(usersReady = true) {
  $("#login-view").hidden = false;
  $("#app-view").hidden = true;
  $("#setup-hint").hidden = usersReady;
}

function showApp(user) {
  currentUser = user;
  $("#login-view").hidden = true;
  $("#app-view").hidden = false;
  $("#user-label").textContent = `${user.username} · ${ROLE_LABELS[user.role] || user.role}`;
  $("#role-pill").textContent = ROLE_LABELS[user.role] || user.role;
  document.body.dataset.role = user.role;
  $$(".owner-only").forEach((el) => {
    el.hidden = user.role !== "owner";
  });
}

function switchPanel(id) {
  $$(".panel").forEach((panel) => panel.classList.toggle("active", panel.id === id));
  $$(".nav-item").forEach((btn) => btn.classList.toggle("active", btn.dataset.panel === id));
  const active = document.querySelector(`.nav-item[data-panel="${id}"]`);
  $("#panel-title").textContent = active ? active.textContent : "控制台";
}

function fieldLabel(key) {
  return FIELD_LABELS[key] || key.replaceAll("_", " ");
}

function renderSettingsDiagnostics(diagnostics) {
  const box = $("#settings-diagnostics");
  if (!box) return;
  box.innerHTML = "";
  if (!diagnostics) {
    box.hidden = true;
    return;
  }

  const groups = [
    ["Webhook 测试", diagnostics.webhooks || []],
    ["DeepSeek API 检查", diagnostics.apis || []],
  ];
  let hasItems = false;
  for (const [title, items] of groups) {
    if (!items.length) continue;
    hasItems = true;
    const section = document.createElement("section");
    const heading = document.createElement("h3");
    heading.textContent = title;
    const list = document.createElement("div");
    list.className = "diagnostics-list";
    for (const item of items) {
      const row = document.createElement("div");
      row.className = `diagnostic-row ${item.ok ? "ok" : "error"}`;
      const name = document.createElement("strong");
      name.textContent = item.name || `${item.purpose || ""} ${item.channel || ""}`.trim();
      const detail = document.createElement("span");
      detail.textContent = item.detail || (item.ok ? "正常" : "失败");
      row.append(name, detail);
      list.appendChild(row);
    }
    section.append(heading, list);
    box.appendChild(section);
  }
  box.hidden = !hasItems;
}

function renderSettings(env) {
  const form = $("#settings-form");
  form.innerHTML = "";
  for (const group of FIELD_GROUPS) {
    const section = document.createElement("section");
    section.className = "settings-section";
    const title = document.createElement("h3");
    title.textContent = group.title;
    section.appendChild(title);
    if (group.description) {
      const description = document.createElement("p");
      description.className = "settings-section-copy";
      description.textContent = group.description;
      section.appendChild(description);
    }
    const grid = document.createElement("div");
    grid.className = "settings-fields";
    for (const key of group.fields) {
      const label = document.createElement("label");
      const isSelect = Boolean(FIELD_OPTIONS[key]);
      label.className = BOOL_KEYS.has(key) ? "setting-toggle" : "field";
      if (isSelect) label.classList.add("field-select");
      if (WIDE_FIELD_KEYS.has(key)) label.classList.add("field-wide");
      label.dataset.key = key;
      const labelText = fieldLabel(key);
      if (BOOL_KEYS.has(key)) {
        const input = document.createElement("input");
        input.type = "checkbox";
        input.name = key;
        input.checked = String(env[key]).toLowerCase() === "true";
        const span = document.createElement("span");
        span.textContent = labelText;
        label.append(input, span);
      } else if (isSelect) {
        const span = document.createElement("span");
        span.textContent = labelText;
        const select = document.createElement("select");
        select.name = key;
        const current = env[key] || "";
        for (const [value, text] of FIELD_OPTIONS[key]) {
          const option = document.createElement("option");
          option.value = value;
          option.textContent = text;
          option.selected = current === value;
          select.appendChild(option);
        }
        if (current && !FIELD_OPTIONS[key].some(([value]) => value === current)) {
          const option = document.createElement("option");
          option.value = current;
          option.textContent = `当前值：${current}`;
          option.selected = true;
          select.appendChild(option);
        }
        label.append(span, select);
      } else {
        const type = key.includes("PORT") || key.includes("SEC") || key === "MAX_BODY_CHARS" ? "number" : "text";
        const span = document.createElement("span");
        span.textContent = labelText;
        const input = document.createElement("input");
        input.type = type;
        input.name = key;
        input.value = env[key] || "";
        input.autocomplete = "off";
        if (SECRET_KEYS.has(key)) {
          input.placeholder = FIELD_PLACEHOLDERS[key] || "当前为空；填写后保存为新值";
        } else if (FIELD_PLACEHOLDERS[key]) {
          input.placeholder = FIELD_PLACEHOLDERS[key];
        }
        label.append(span, input);
      }
      grid.appendChild(label);
    }
    section.appendChild(grid);
    form.appendChild(section);
  }
}

function collectSettings() {
  const env = {};
  for (const input of $("#settings-form").elements) {
    if (!input.name) continue;
    env[input.name] = input.type === "checkbox" ? String(input.checked) : input.value.trim();
  }
  return {
    env,
    prompts: collectPrompts(),
  };
}

function fillPrompts(prompts) {
  $("#business-summary").value = prompts.business_summary_system || "";
  $("#business-filter").value = prompts.business_filter_system || "";
  $("#summary-system").value = prompts.summary_system || "";
  $("#filter-system").value = prompts.filter_system || "";
}

function collectPrompts() {
  const prompts = {
    business_summary_system: $("#business-summary").value,
    business_filter_system: $("#business-filter").value,
  };
  if (currentUser?.role === "owner") {
    prompts.summary_system = $("#summary-system").value;
    prompts.filter_system = $("#filter-system").value;
  }
  return prompts;
}

async function loadPrompts() {
  const data = await api("/api/prompts");
  fillPrompts(data.prompts || {});
}

async function loadOwnerSettings() {
  if (currentUser?.role !== "owner") return;
  const data = await api("/api/settings");
  renderSettings(data.env || {});
  fillPrompts(data.prompts || {});
  $("#paths").textContent = `.env: ${data.env_path || ""} · prompts: ${data.prompts_path || ""}`;
  settingsSnapshot = JSON.stringify(collectSettings());
}

async function savePrompts() {
  await api("/api/prompts", {
    method: "POST",
    body: JSON.stringify({ prompts: collectPrompts() }),
  });
  toast("提示词已保存");
}

async function saveSettings() {
  const data = await api("/api/settings", {
    method: "POST",
    body: JSON.stringify(collectSettings()),
  });
  toast(data.message || "设置已保存。");
  renderSettingsDiagnostics(data.diagnostics);
  await loadOwnerSettings();
}

function renderRagFiles(files) {
  const list = $("#rag-files");
  list.innerHTML = "";
  if (!files.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "还没有知识库文件。";
    list.appendChild(empty);
    return;
  }
  for (const file of files) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "file-item";
    const name = document.createElement("strong");
    name.textContent = file.path;
    const size = document.createElement("span");
    size.textContent = `${file.size} 字节`;
    btn.append(name, size);
    btn.addEventListener("click", () => loadRagFile(file.path));
    list.appendChild(btn);
  }
}

async function loadRagFiles() {
  const data = await api("/api/rag/files");
  renderRagFiles(data.files || []);
}

async function loadRagFile(path) {
  const data = await api(`/api/rag/file?path=${encodeURIComponent(path)}`);
  $("#rag-path").value = data.file.path;
  $("#rag-content").value = data.file.content;
  $("#rag-meta").textContent = `已载入 ${data.file.path}`;
}

async function saveRagFile() {
  const path = $("#rag-path").value.trim();
  if (!path) {
    toast("请先填写文件路径", false);
    return;
  }
  const data = await api("/api/rag/file", {
    method: "POST",
    body: JSON.stringify({
      path,
      content: $("#rag-content").value,
    }),
  });
  toast(data.message || "知识库文件已保存");
  $("#rag-meta").textContent = `已保存 ${data.file.path}`;
  await loadRagFiles();
}

async function bootstrap() {
  const data = await api("/api/session");
  csrfToken = data.csrf_token || "";
  if (!data.user) {
    showLogin(data.users_ready !== false);
    return;
  }
  showApp(data.user);
  await Promise.all([loadPrompts(), loadRagFiles(), loadOwnerSettings()]);
}

$("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  try {
    const data = await api("/api/login", {
      method: "POST",
      body: JSON.stringify({
        username: form.get("username"),
        password: form.get("password"),
      }),
    });
    csrfToken = data.csrf_token || "";
    showApp(data.user);
    await Promise.all([loadPrompts(), loadRagFiles(), loadOwnerSettings()]);
  } catch (err) {
    toast(err.message || "登录失败", false);
  }
});

$("#logout-btn").addEventListener("click", async () => {
  await api("/api/logout", { method: "POST", body: "{}" }).catch(() => {});
  csrfToken = "";
  currentUser = null;
  showLogin(true);
});

$$(".nav-item").forEach((btn) => {
  btn.addEventListener("click", () => switchPanel(btn.dataset.panel));
});

$("#save-prompts-btn").addEventListener("click", () => savePrompts().catch((err) => toast(err.message, false)));
$("#save-settings-btn").addEventListener("click", () => saveSettings().catch((err) => toast(err.message, false)));
$("#refresh-rag-btn").addEventListener("click", () => loadRagFiles().catch((err) => toast(err.message, false)));
$("#save-rag-btn").addEventListener("click", () => saveRagFile().catch((err) => toast(err.message, false)));
$("#new-rag-btn").addEventListener("click", () => {
  $("#rag-path").value = "";
  $("#rag-content").value = "# 新的 AEBBS 知识条目\n\n";
  $("#rag-meta").textContent = "新文件";
});

bootstrap().catch((err) => {
  showLogin(true);
  toast(err.message || "无法载入控制台", false);
});
