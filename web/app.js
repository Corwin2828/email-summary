const ENV_KEYS = [
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
  "IMAP_USE_IDLE",
  "POLL_INTERVAL_SEC",
  "MAX_BODY_CHARS",
  "FILTER_MODE",
  "NOTIFY_FORMAT",
  "PROCESS_EXISTING_UNREAD",
  "CATCHUP_SINCE_LAST_RUN",
];

const BOOL_KEYS = new Set([
  "GMAIL_ENABLED",
  "OUTLOOK_ENABLED",
  "OUTLOOK_USE_OAUTH",
  "IMAP_USE_IDLE",
  "PROCESS_EXISTING_UNREAD",
  "CATCHUP_SINCE_LAST_RUN",
]);

const form = document.getElementById("settings-form");
const toast = document.getElementById("toast");
const pathsEl = document.getElementById("paths");
const saveBar = document.getElementById("save-bar");
const saveButtons = [
  document.getElementById("save-btn"),
  document.getElementById("save-btn-bottom"),
].filter(Boolean);

let snapshot = "";

function showToast(msg, ok = true) {
  toast.textContent = msg;
  toast.className = `toast ${ok ? "ok" : "err"}`;
  clearTimeout(showToast._timer);
  showToast._timer = setTimeout(() => toast.classList.add("hidden"), 4500);
}

function setBoolField(name, value) {
  const el = form.elements[name];
  if (el) el.checked = ["1", "true", "yes", "on"].includes(String(value).toLowerCase());
}

function getBoolField(name) {
  const el = form.elements[name];
  return el && el.checked ? "true" : "false";
}

function collectPayload() {
  const env = {};
  for (const key of ENV_KEYS) {
    if (BOOL_KEYS.has(key)) {
      env[key] = getBoolField(key);
    } else if (form.elements[key]) {
      env[key] = form.elements[key].value.trim();
    }
  }
  return {
    env,
    prompts: {
      summary_system: form.elements.summary_system.value,
      filter_system: form.elements.filter_system.value,
    },
  };
}

function serializeForm() {
  return JSON.stringify(collectPayload());
}

function setDirty(dirty) {
  saveBar.classList.toggle("visible", dirty);
  document.body.classList.toggle("has-unsaved", dirty);
}

function fillForm(data) {
  const env = data.env || {};
  for (const key of ENV_KEYS) {
    if (BOOL_KEYS.has(key)) {
      setBoolField(key, env[key]);
    } else if (form.elements[key]) {
      form.elements[key].value = env[key] || "";
    }
  }
  const prompts = data.prompts || {};
  form.elements.summary_system.value = prompts.summary_system || "";
  form.elements.filter_system.value = prompts.filter_system || "";
  pathsEl.textContent = `.env → ${data.env_path || ""}  ·  prompts → ${data.prompts_path || ""}`;
  snapshot = serializeForm();
  setDirty(false);
}

function setSaving(saving) {
  for (const btn of saveButtons) {
    btn.disabled = saving;
    btn.classList.toggle("loading", saving);
    const label = btn.querySelector(".btn-label");
    if (label) label.textContent = saving ? "保存中…" : "保存设置";
  }
}

async function loadSettings() {
  const res = await fetch("/api/settings");
  if (!res.ok) throw new Error("load failed");
  const data = await res.json();
  fillForm(data);
}

async function saveSettings() {
  setSaving(true);
  try {
    const payload = collectPayload();
    const res = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (data.ok) {
      showToast(data.message || "保存成功，请重启邮件助手", true);
      await loadSettings();
    } else {
      showToast((data.errors || ["保存失败"]).join("；"), false);
    }
  } catch {
    showToast("保存失败，请检查服务是否在运行", false);
  } finally {
    setSaving(false);
  }
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  saveSettings();
});

form.addEventListener("input", () => {
  setDirty(serializeForm() !== snapshot);
});

form.addEventListener("change", () => {
  setDirty(serializeForm() !== snapshot);
});

for (const id of ["reload-btn", "reload-btn-bottom"]) {
  document.getElementById(id)?.addEventListener("click", () => {
    loadSettings()
      .then(() => showToast("已重新加载配置", true))
      .catch(() => showToast("无法加载配置", false));
  });
}

loadSettings().catch(() => showToast("无法加载配置，请确认已运行 打开设置.command", false));
