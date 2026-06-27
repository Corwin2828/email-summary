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
    title: "AEBBS business channel",
    fields: [
      "BUSINESS_EMAIL_ENABLED",
      "BUSINESS_EMAIL_NAME",
      "BUSINESS_EMAIL_ADDRESS",
      "BUSINESS_EMAIL_IMAP_HOST",
      "BUSINESS_EMAIL_IMAP_PORT",
      "BUSINESS_EMAIL_PASSWORD",
      "BUSINESS_POLL_INTERVAL_SEC",
      "BUSINESS_IMAP_RETRY_WAIT_SEC",
      "BUSINESS_RETRY_FAILED_AFTER_SEC",
      "BUSINESS_PROCESS_EXISTING_UNREAD",
      "BUSINESS_BYPASS_FILTER",
      "BUSINESS_QUIET_HOURS_ENABLED",
      "BUSINESS_FEISHU_WEBHOOK_URL",
      "BUSINESS_WECOM_WEBHOOK_URL",
      "BUSINESS_DEEPSEEK_API_KEY",
      "BUSINESS_DEEPSEEK_BASE_URL",
      "BUSINESS_DEEPSEEK_MODEL",
      "BUSINESS_KNOWLEDGE_DIR",
    ],
  },
  {
    title: "Personal mail",
    fields: [
      "DEEPSEEK_API_KEY",
      "DEEPSEEK_BASE_URL",
      "DEEPSEEK_MODEL",
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
    title: "Runtime",
    fields: [
      "IMAP_USE_IDLE",
      "POLL_INTERVAL_SEC",
      "IMAP_OVERQUOTA_WAIT_SEC",
      "HEARTBEAT_ALERT_ENABLED",
      "HEARTBEAT_STALL_SEC",
      "HEARTBEAT_CHECK_SEC",
      "DATA_DIR",
      "MAX_BODY_CHARS",
      "FILTER_MODE",
      "NOTIFY_FORMAT",
      "DAILY_DIGEST_ENABLED",
      "DAILY_DIGEST_TIME",
      "PROCESS_EXISTING_UNREAD",
      "CATCHUP_SINCE_LAST_RUN",
      "WEB_HOST",
      "WEB_PORT",
    ],
  },
];

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
    throw new Error(data.error || (data.errors || ["Request failed"]).join("; "));
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
  $("#user-label").textContent = `${user.username} · ${user.role}`;
  $("#role-pill").textContent = user.role;
  document.body.dataset.role = user.role;
  $$(".owner-only").forEach((el) => {
    el.hidden = user.role !== "owner";
  });
}

function switchPanel(id) {
  $$(".panel").forEach((panel) => panel.classList.toggle("active", panel.id === id));
  $$(".nav-item").forEach((btn) => btn.classList.toggle("active", btn.dataset.panel === id));
  const active = document.querySelector(`.nav-item[data-panel="${id}"]`);
  $("#panel-title").textContent = active ? active.textContent : "Console";
}

function fieldLabel(key) {
  return key.replaceAll("_", " ").toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase());
}

function renderSettings(env) {
  const form = $("#settings-form");
  form.innerHTML = "";
  for (const group of FIELD_GROUPS) {
    const section = document.createElement("section");
    section.className = "settings-section";
    section.innerHTML = `<h3>${group.title}</h3>`;
    const grid = document.createElement("div");
    grid.className = "settings-fields";
    for (const key of group.fields) {
      const label = document.createElement("label");
      label.className = BOOL_KEYS.has(key) ? "setting-toggle" : "field";
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
      } else {
        const type = SECRET_KEYS.has(key) ? "password" : key.includes("PORT") || key.includes("SEC") || key === "MAX_BODY_CHARS" ? "number" : "text";
        const span = document.createElement("span");
        span.textContent = labelText;
        const input = document.createElement("input");
        input.type = type;
        input.name = key;
        input.value = env[key] || "";
        input.autocomplete = "off";
        if (SECRET_KEYS.has(key)) {
          input.placeholder = "Leave blank to keep existing value";
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
  toast("Prompt saved");
}

async function saveSettings() {
  await api("/api/settings", {
    method: "POST",
    body: JSON.stringify(collectSettings()),
  });
  toast("Settings saved. Restart the mail service to apply runtime changes.");
  await loadOwnerSettings();
}

function renderRagFiles(files) {
  const list = $("#rag-files");
  list.innerHTML = "";
  if (!files.length) {
    list.innerHTML = `<p class="empty">No knowledge files yet.</p>`;
    return;
  }
  for (const file of files) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "file-item";
    btn.innerHTML = `<strong>${file.path}</strong><span>${file.size} bytes</span>`;
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
  $("#rag-meta").textContent = `Loaded ${data.file.path}`;
}

async function saveRagFile() {
  const path = $("#rag-path").value.trim();
  if (!path) {
    toast("Please enter a file path", false);
    return;
  }
  const data = await api("/api/rag/file", {
    method: "POST",
    body: JSON.stringify({
      path,
      content: $("#rag-content").value,
    }),
  });
  toast(data.message || "Knowledge file saved");
  $("#rag-meta").textContent = `Saved ${data.file.path}`;
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
    toast(err.message || "Login failed", false);
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
  $("#rag-content").value = "# New AEBBS knowledge note\n\n";
  $("#rag-meta").textContent = "New file";
});

bootstrap().catch((err) => {
  showLogin(true);
  toast(err.message || "Unable to load console", false);
});
