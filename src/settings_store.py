from __future__ import annotations

import os
import re
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

from src.config import PROJECT_ROOT, ENV_PATH, resolve_data_dir
from src.prompts import load_prompts, prompts_path, save_prompts

# 页面可编辑的全部 .env 键
ENV_KEYS = [
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_MODEL",
    "BUSINESS_DEEPSEEK_API_KEY",
    "BUSINESS_DEEPSEEK_BASE_URL",
    "BUSINESS_DEEPSEEK_MODEL",
    "GMAIL_ENABLED",
    "GMAIL_ADDRESS",
    "GMAIL_APP_PASSWORD",
    "OUTLOOK_ENABLED",
    "OUTLOOK_ADDRESS",
    "OUTLOOK_USE_OAUTH",
    "AZURE_CLIENT_ID",
    "OUTLOOK_APP_PASSWORD",
    "BUSINESS_EMAIL_ENABLED",
    "BUSINESS_EMAIL_NAME",
    "BUSINESS_EMAIL_ADDRESS",
    "BUSINESS_EMAIL_IMAP_HOST",
    "BUSINESS_EMAIL_IMAP_PORT",
    "BUSINESS_EMAIL_PASSWORD",
    "BUSINESS_POLL_INTERVAL_SEC",
    "BUSINESS_IMAP_RETRY_WAIT_SEC",
    "BUSINESS_QUIET_HOURS_ENABLED",
    "BUSINESS_PROCESS_EXISTING_UNREAD",
    "BUSINESS_RETRY_FAILED_AFTER_SEC",
    "BUSINESS_BYPASS_FILTER",
    "FEISHU_WEBHOOK_URL",
    "WECOM_WEBHOOK_URL",
    "BUSINESS_FEISHU_WEBHOOK_URL",
    "BUSINESS_WECOM_WEBHOOK_URL",
    "BUSINESS_KNOWLEDGE_DIR",
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
    "WEB_MAX_CONTENT_LENGTH",
    "WEB_RAG_MAX_FILE_BYTES",
    "WEB_LOGIN_MAX_ATTEMPTS",
    "WEB_LOGIN_WINDOW_SEC",
    "WEB_COOKIE_SECURE",
]

SECRET_KEYS = {
    "DEEPSEEK_API_KEY",
    "BUSINESS_DEEPSEEK_API_KEY",
    "GMAIL_APP_PASSWORD",
    "OUTLOOK_APP_PASSWORD",
    "BUSINESS_EMAIL_PASSWORD",
    "FEISHU_WEBHOOK_URL",
    "WECOM_WEBHOOK_URL",
    "BUSINESS_FEISHU_WEBHOOK_URL",
    "BUSINESS_WECOM_WEBHOOK_URL",
}


def _format_env_value(value: str) -> str:
    """避免含特殊字符的值破坏 .env 格式。"""
    if value == "":
        return ""
    if re.search(r'[\s#\\="\']', value):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def read_env_dict(reveal_secrets: bool = False) -> dict[str, str]:
    if not ENV_PATH.exists():
        return {k: "" for k in ENV_KEYS}
    values = dotenv_values(ENV_PATH)
    result: dict[str, str] = {}
    for key in ENV_KEYS:
        if key in SECRET_KEYS and not reveal_secrets:
            result[key] = ""
        else:
            result[key] = values.get(key) or ""
    return result


def _merge_existing_secrets(env: dict[str, str]) -> dict[str, str]:
    if not ENV_PATH.exists():
        return env
    values = dotenv_values(ENV_PATH)
    merged = dict(env)
    for key in SECRET_KEYS:
        if key not in merged or merged[key] == "":
            current = values.get(key) or ""
            if current:
                merged[key] = current
    return merged


def update_env_file(updates: dict[str, str]) -> None:
    """更新 .env 中已有键，保留注释与顺序；新键追加到末尾。"""
    if not ENV_PATH.exists():
        ENV_PATH.write_text("# Email Summary\n", encoding="utf-8")

    lines = ENV_PATH.read_text(encoding="utf-8").splitlines(keepends=True)
    seen: set[str] = set()
    out: list[str] = []

    for line in lines:
        raw = line.rstrip("\n\r")
        if raw.strip() and not raw.strip().startswith("#") and "=" in raw:
            key = raw.split("=", 1)[0].strip()
            if key in updates:
                out.append(f"{key}={_format_env_value(updates[key])}\n")
                seen.add(key)
                continue
        out.append(line if line.endswith("\n") else line + "\n")

    for key in ENV_KEYS:
        if key in updates and key not in seen:
            out.append(f"{key}={_format_env_value(updates[key])}\n")

    ENV_PATH.write_text("".join(out), encoding="utf-8")


def _normalize_env_updates(updates: dict[str, str]) -> dict[str, str]:
    cleaned = {k: str(v).strip() for k, v in updates.items() if k in ENV_KEYS}
    for key in list(cleaned):
        if key in SECRET_KEYS and cleaned[key] == "":
            cleaned.pop(key)
    if "GMAIL_APP_PASSWORD" in cleaned:
        cleaned["GMAIL_APP_PASSWORD"] = cleaned["GMAIL_APP_PASSWORD"].replace(
            " ", ""
        )
    if "GMAIL_ADDRESS" in cleaned and cleaned["GMAIL_ADDRESS"]:
        cleaned["GMAIL_ADDRESS"] = cleaned["GMAIL_ADDRESS"].lower()
    if "OUTLOOK_ADDRESS" in cleaned and cleaned["OUTLOOK_ADDRESS"]:
        cleaned["OUTLOOK_ADDRESS"] = cleaned["OUTLOOK_ADDRESS"].lower()
    if "BUSINESS_EMAIL_ADDRESS" in cleaned and cleaned["BUSINESS_EMAIL_ADDRESS"]:
        cleaned["BUSINESS_EMAIL_ADDRESS"] = cleaned["BUSINESS_EMAIL_ADDRESS"].lower()
    return cleaned


def read_all_settings(reveal_secrets: bool = False) -> dict:
    env = read_env_dict(reveal_secrets=reveal_secrets)
    data_dir = resolve_data_dir(env.get("DATA_DIR") or None)
    prompts = load_prompts(data_dir)
    return {
        "env": env,
        "prompts": prompts,
        "env_path": str(ENV_PATH),
        "prompts_path": str(prompts_path(data_dir)),
    }


def save_all_settings(payload: dict) -> None:
    cleaned = _normalize_env_updates(payload.get("env") or {})
    update_env_file(cleaned)

    load_dotenv(ENV_PATH, override=True)
    data_dir = resolve_data_dir(cleaned.get("DATA_DIR") or None)

    prompts = payload.get("prompts") or {}
    save_prompts(
        prompts.get("summary_system", ""),
        prompts.get("filter_system", ""),
        prompts.get("business_summary_system", ""),
        prompts.get("business_filter_system", ""),
        data_dir,
    )


def read_prompt_settings(owner: bool = False) -> dict[str, str]:
    env = read_env_dict()
    data_dir = resolve_data_dir(env.get("DATA_DIR") or None)
    prompts = load_prompts(data_dir)
    if owner:
        return prompts
    return {
        "business_summary_system": prompts.get("business_summary_system", ""),
        "business_filter_system": prompts.get("business_filter_system", ""),
    }


def save_prompt_settings(payload: dict, owner: bool = False) -> None:
    env = read_env_dict()
    data_dir = resolve_data_dir(env.get("DATA_DIR") or None)
    current = load_prompts(data_dir)
    updates = payload.get("prompts") or {}
    allowed = {
        "business_summary_system",
        "business_filter_system",
    }
    if owner:
        allowed.update({"summary_system", "filter_system"})

    for key, value in updates.items():
        if key in allowed:
            current[key] = str(value)

    save_prompts(
        current.get("summary_system", ""),
        current.get("filter_system", ""),
        current.get("business_summary_system", ""),
        current.get("business_filter_system", ""),
        data_dir,
    )


def validate_settings(payload: dict) -> list[str]:
    errors: list[str] = []
    env = _merge_existing_secrets(
        _normalize_env_updates(payload.get("env") or {})
    )

    def validate_int(
        key: str,
        label: str,
        minimum: int,
        maximum: int | None = None,
    ) -> None:
        raw = env.get(key, "").strip()
        if not raw:
            return
        try:
            num = int(raw)
        except ValueError:
            errors.append(f"{label}必须是数字")
            return
        if num < minimum:
            errors.append(f"{label}不能小于 {minimum}")
        if maximum is not None and num > maximum:
            errors.append(f"{label}不能大于 {maximum}")

    if not env.get("DEEPSEEK_API_KEY"):
        errors.append("DeepSeek API Key 不能为空")

    gmail_on = env.get("GMAIL_ENABLED", "").lower() in ("1", "true", "yes")
    outlook_on = env.get("OUTLOOK_ENABLED", "").lower() in (
        "1",
        "true",
        "yes",
    )
    business_on = env.get("BUSINESS_EMAIL_ENABLED", "").lower() in (
        "1",
        "true",
        "yes",
    )
    if not gmail_on and not outlook_on and not business_on:
        errors.append("请至少启用 Gmail、Outlook 或 AEBBS 企业邮箱之一")

    if gmail_on:
        if not env.get("GMAIL_ADDRESS"):
            errors.append("Gmail 地址不能为空")
        if not env.get("GMAIL_APP_PASSWORD"):
            errors.append("Gmail 应用专用密码不能为空")

    if outlook_on:
        if not env.get("OUTLOOK_ADDRESS"):
            errors.append("Outlook 地址不能为空")
        use_oauth = env.get("OUTLOOK_USE_OAUTH", "").lower() in (
            "1",
            "true",
            "yes",
        )
        if use_oauth and not env.get("AZURE_CLIENT_ID"):
            errors.append("Outlook OAuth 需要填写 Azure Client ID")
        if not use_oauth and not env.get("OUTLOOK_APP_PASSWORD"):
            errors.append("请填写 Outlook 应用密码，或开启 OAuth")

    feishu = env.get("FEISHU_WEBHOOK_URL", "")
    wecom = env.get("WECOM_WEBHOOK_URL", "")
    if (gmail_on or outlook_on) and not feishu and not wecom:
        errors.append("个人邮箱启用时，请至少填写飞书或企业微信 Webhook")

    if business_on:
        if not env.get("BUSINESS_EMAIL_NAME"):
            errors.append("AEBBS 企业邮箱账户名不能为空")
        if not env.get("BUSINESS_EMAIL_ADDRESS"):
            errors.append("AEBBS 企业邮箱地址不能为空")
        if not env.get("BUSINESS_EMAIL_IMAP_HOST"):
            errors.append("AEBBS 企业邮箱 IMAP 服务器不能为空")
        if not env.get("BUSINESS_EMAIL_PASSWORD"):
            errors.append("AEBBS 企业邮箱密码不能为空")
        if not env.get("BUSINESS_DEEPSEEK_API_KEY"):
            errors.append("AEBBS 企业邮箱需要填写独立模型 API Key")
        if not env.get("BUSINESS_FEISHU_WEBHOOK_URL") and not env.get(
            "BUSINESS_WECOM_WEBHOOK_URL"
        ):
            errors.append("AEBBS 企业邮箱需要填写独立飞书或企业微信 Webhook")
        for key, label, minimum in (
            ("BUSINESS_EMAIL_IMAP_PORT", "AEBBS IMAP 端口", 1),
            ("BUSINESS_POLL_INTERVAL_SEC", "AEBBS 轮询间隔秒数", 30),
            ("BUSINESS_IMAP_RETRY_WAIT_SEC", "AEBBS IMAP 重试等待秒数", 60),
            ("BUSINESS_RETRY_FAILED_AFTER_SEC", "AEBBS 处理失败重试秒数", 30),
        ):
            validate_int(key, label, minimum)

    try:
        poll = int(env.get("POLL_INTERVAL_SEC") or "1800")
        if poll < 900:
            errors.append("轮询间隔建议不少于 900 秒（15 分钟）")
    except ValueError:
        errors.append("轮询间隔必须是数字")

    if env.get("DAILY_DIGEST_ENABLED", "").lower() in ("1", "true", "yes"):
        digest_time = (env.get("DAILY_DIGEST_TIME") or "").strip()
        if not re.match(r"^(?:[01]\d|2[0-3]):[0-5]\d$", digest_time):
            errors.append("每日简报时间格式应为 HH:MM（例如 21:30）")

    for key, label, minimum in (
        ("IMAP_OVERQUOTA_WAIT_SEC", "Gmail 限流等待秒数", 60),
        ("HEARTBEAT_STALL_SEC", "卡住告警阈值秒数", 300),
        ("HEARTBEAT_CHECK_SEC", "心跳检查间隔秒数", 60),
        ("MAX_BODY_CHARS", "送入模型的最大正文字符数", 1000),
        ("WEB_MAX_CONTENT_LENGTH", "网页请求体大小限制", 1024),
        ("WEB_RAG_MAX_FILE_BYTES", "知识库单文件大小限制", 1),
        ("WEB_LOGIN_MAX_ATTEMPTS", "登录失败次数限制", 1),
        ("WEB_LOGIN_WINDOW_SEC", "登录失败统计窗口秒数", 60),
    ):
        validate_int(key, label, minimum)

    validate_int("WEB_PORT", "网页端口", 1, 65535)

    return errors
