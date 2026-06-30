from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from openai import OpenAI

from src.config import AppConfig
from src.notify import send_text_all

LOCAL_TZ = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _now_label() -> str:
    return datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _safe_error(exc: Exception, secrets: list[str]) -> str:
    text = str(exc) or exc.__class__.__name__
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[已隐藏]")
    return text[:240]


def _configured_secrets(config: AppConfig) -> list[str]:
    return [
        config.deepseek_api_key,
        config.business_deepseek_api_key,
        config.feishu_webhook or "",
        config.wecom_webhook or "",
        config.business_feishu_webhook or "",
        config.business_wecom_webhook or "",
    ]


def _check_deepseek(
    name: str,
    api_key: str,
    base_url: str,
    model: str,
    secrets: list[str],
) -> CheckResult:
    if not api_key:
        return CheckResult(name, False, "未配置 API Key")
    try:
        client = OpenAI(api_key=api_key, base_url=base_url)
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "只回复 OK。"},
                {"role": "user", "content": "连通性测试"},
            ],
            temperature=0,
            max_tokens=8,
            timeout=20,
        )
        content = (resp.choices[0].message.content or "").strip()
        if not content:
            return CheckResult(name, False, "API 返回为空")
        return CheckResult(name, True, "API 可用")
    except Exception as e:
        return CheckResult(name, False, f"API 不可用: {_safe_error(e, secrets)}")


def check_deepseek_apis(config: AppConfig) -> list[CheckResult]:
    secrets = _configured_secrets(config)
    checks = [
        _check_deepseek(
            "个人邮箱 DeepSeek",
            config.deepseek_api_key,
            config.deepseek_base_url,
            config.deepseek_model,
            secrets,
        )
    ]
    if any(acc.purpose == "business" for acc in config.accounts):
        checks.append(
            _check_deepseek(
                "AEBBS 企业邮箱 DeepSeek",
                config.business_deepseek_api_key,
                config.business_deepseek_base_url,
                config.business_deepseek_model,
                secrets,
            )
        )
    return checks


def notify_settings_saved(
    config: AppConfig,
    username: str,
    changed_items: list[str],
) -> list[dict[str, object]]:
    changed = "、".join(changed_items[:20]) if changed_items else "未检测到字段变化"
    if len(changed_items) > 20:
        changed += f" 等 {len(changed_items)} 项"
    text = "\n".join(
        [
            "【邮件总结助手设置已更新】",
            f"时间: {_now_label()}",
            f"操作账号: {username}",
            f"变更项: {changed}",
            "这条消息也是 Webhook 连通性测试；能收到即表示该渠道可用。",
        ]
    )
    return [result.to_dict() for result in send_text_all(config, text)]


def notify_system_started(config: AppConfig) -> list[dict[str, object]]:
    accounts = "、".join(acc.name for acc in config.accounts)
    text = "\n".join(
        [
            "【邮件总结助手已启动】",
            f"时间: {_now_label()}",
            f"监听账户: {accounts}",
            f"过滤模式: {config.filter_mode}",
            f"通知格式: {config.notify_format}",
            "如果你能收到这条消息，说明启动时 Webhook 可用。",
        ]
    )
    return [result.to_dict() for result in send_text_all(config, text)]


def notify_system_issue(
    config: AppConfig,
    title: str,
    detail: str,
) -> list[dict[str, object]]:
    text = "\n".join(
        [
            f"【邮件总结助手告警】{title}",
            f"时间: {_now_label()}",
            detail[:1200],
        ]
    )
    return [result.to_dict() for result in send_text_all(config, text)]


def run_settings_diagnostics(
    config: AppConfig,
    username: str,
    changed_items: list[str],
) -> dict[str, list[dict[str, object]]]:
    webhook_results = notify_settings_saved(config, username, changed_items)
    api_results = [result.to_dict() for result in check_deepseek_apis(config)]
    return {
        "webhooks": webhook_results,
        "apis": api_results,
    }
