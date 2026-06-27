from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"

load_dotenv(ENV_PATH, override=True)


def _bool(val: str | None, default: bool = False) -> bool:
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def resolve_data_dir(raw: str | None = None) -> Path:
    path = Path(raw or os.getenv("DATA_DIR", "./data"))
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass(frozen=True)
class AccountConfig:
    name: str
    host: str
    port: int
    address: str
    password: str = ""
    use_oauth: bool = False
    azure_client_id: str = ""
    token_cache_path: Path | None = None
    purpose: str = "personal"
    poll_interval_sec: int | None = None
    quiet_hours_enabled: bool = True
    overquota_wait_sec: int | None = None


@dataclass(frozen=True)
class AppConfig:
    deepseek_api_key: str
    deepseek_base_url: str
    deepseek_model: str
    business_deepseek_api_key: str
    business_deepseek_base_url: str
    business_deepseek_model: str
    accounts: list[AccountConfig]
    feishu_webhook: str | None
    wecom_webhook: str | None
    business_feishu_webhook: str | None
    business_wecom_webhook: str | None
    poll_interval_sec: int
    data_dir: Path
    max_body_chars: int
    filter_mode: str
    notify_format: str
    daily_digest_enabled: bool
    daily_digest_time: str
    process_existing_unread: bool
    catchup_since_last_run: bool
    imap_use_idle: bool
    imap_overquota_wait_sec: int
    heartbeat_alert_enabled: bool
    heartbeat_stall_sec: int
    heartbeat_check_sec: int
    forward_source_map: dict[str, str]


def _resolve_filter_mode() -> str:
    """ai=全部由 DeepSeek 判断是否总结；rules=本地规则（旧模式）。"""
    raw = os.getenv("FILTER_MODE", "").strip().lower()
    if raw in ("ai", "rules"):
        return raw
    if _bool(os.getenv("AI_FILTER")):
        return "ai"
    if os.getenv("VERIFICATION_FILTER", "").strip().lower() == "ai":
        return "ai"
    if os.getenv("AI_FILTER") is not None and not _bool(os.getenv("AI_FILTER")):
        return "rules"
    if os.getenv("VERIFICATION_FILTER", "").strip().lower() == "strict":
        return "rules"
    return "ai"


def _resolve_notify_format() -> str:
    """ai=DeepSeek 生成整段推送文案；template=本地模板拼装。"""
    raw = os.getenv("NOTIFY_FORMAT", "").strip().lower()
    if raw in ("ai", "template"):
        return raw
    return "ai"


def _resolve_daily_digest_time() -> str:
    raw = os.getenv("DAILY_DIGEST_TIME", "21:30").strip()
    if not raw:
        return "21:30"
    return raw


def _parse_forward_source_map() -> dict[str, str]:
    """FORWARD_SOURCE_MAP=addr:名称,addr2:名称2"""
    raw = os.getenv("FORWARD_SOURCE_MAP", "").strip()
    result: dict[str, str] = {}
    if not raw:
        return result
    for part in raw.split(","):
        part = part.strip()
        if ":" not in part:
            continue
        addr, label = part.split(":", 1)
        addr = addr.strip().lower()
        label = label.strip()
        if addr and label:
            result[addr] = label
    return result


def _int_env(name: str, default: int, minimum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, value)


def load_config() -> AppConfig:
    accounts: list[AccountConfig] = []
    data_dir = resolve_data_dir()

    if _bool(os.getenv("GMAIL_ENABLED")):
        addr = os.getenv("GMAIL_ADDRESS", "").strip().lower()
        pwd = os.getenv("GMAIL_APP_PASSWORD", "").replace(" ", "")
        if not addr or not pwd:
            raise ValueError(
                "Gmail 已启用：请填写 GMAIL_ADDRESS 与 GMAIL_APP_PASSWORD"
            )
        accounts.append(
            AccountConfig("gmail", "imap.gmail.com", 993, addr, pwd)
        )

    if _bool(os.getenv("OUTLOOK_ENABLED")):
        addr = os.getenv("OUTLOOK_ADDRESS", "").strip().lower()
        use_oauth = _bool(os.getenv("OUTLOOK_USE_OAUTH"), default=True)
        pwd = os.getenv("OUTLOOK_APP_PASSWORD", "").strip()
        client_id = os.getenv("AZURE_CLIENT_ID", "").strip()

        if not addr:
            raise ValueError("Outlook 已启用：请填写 OUTLOOK_ADDRESS")
        if use_oauth:
            if not client_id:
                raise ValueError(
                    "Outlook OAuth 模式需要 AZURE_CLIENT_ID，"
                    "请按 README 注册 Azure 应用后填入"
                )
            accounts.append(
                AccountConfig(
                    name="outlook",
                    host="outlook.office365.com",
                    port=993,
                    address=addr,
                    use_oauth=True,
                    azure_client_id=client_id,
                    token_cache_path=data_dir / "outlook_msal_cache.json",
                )
            )
        elif pwd:
            accounts.append(
                AccountConfig(
                    "outlook", "outlook.office365.com", 993, addr, pwd
                )
            )
        else:
            raise ValueError(
                "Outlook 已启用：请设置 AZURE_CLIENT_ID（OAuth）"
                "或 OUTLOOK_APP_PASSWORD"
            )

    if _bool(os.getenv("BUSINESS_EMAIL_ENABLED")):
        name = os.getenv("BUSINESS_EMAIL_NAME", "aebbs-support").strip()
        addr = os.getenv("BUSINESS_EMAIL_ADDRESS", "").strip().lower()
        host = os.getenv("BUSINESS_EMAIL_IMAP_HOST", "").strip()
        pwd = os.getenv("BUSINESS_EMAIL_PASSWORD", "").strip()
        port = _int_env("BUSINESS_EMAIL_IMAP_PORT", 993, 1)
        poll_sec = _int_env("BUSINESS_POLL_INTERVAL_SEC", 60, 30)
        overquota_sec = _int_env("BUSINESS_IMAP_RETRY_WAIT_SEC", 300, 60)

        if not name:
            raise ValueError("企业邮箱已启用：请填写 BUSINESS_EMAIL_NAME")
        if not addr:
            raise ValueError("企业邮箱已启用：请填写 BUSINESS_EMAIL_ADDRESS")
        if not host:
            raise ValueError("企业邮箱已启用：请填写 BUSINESS_EMAIL_IMAP_HOST")
        if not pwd:
            raise ValueError("企业邮箱已启用：请填写 BUSINESS_EMAIL_PASSWORD")
        if any(acc.name == name for acc in accounts):
            raise ValueError(f"邮箱账户名重复：{name}")

        accounts.append(
            AccountConfig(
                name=name,
                host=host,
                port=port,
                address=addr,
                password=pwd,
                purpose="business",
                poll_interval_sec=poll_sec,
                quiet_hours_enabled=_bool(
                    os.getenv("BUSINESS_QUIET_HOURS_ENABLED"),
                    default=False,
                ),
                overquota_wait_sec=overquota_sec,
            )
        )

    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise ValueError("请在 .env 中设置 DEEPSEEK_API_KEY")

    if not accounts:
        raise ValueError("请至少启用并配置一个邮箱（Gmail、Outlook 或 AEBBS 企业邮箱）")

    feishu = os.getenv("FEISHU_WEBHOOK_URL", "").strip() or None
    wecom = os.getenv("WECOM_WEBHOOK_URL", "").strip() or None
    business_feishu = os.getenv("BUSINESS_FEISHU_WEBHOOK_URL", "").strip() or None
    business_wecom = os.getenv("BUSINESS_WECOM_WEBHOOK_URL", "").strip() or None

    has_personal = any(acc.purpose == "personal" for acc in accounts)
    has_business = any(acc.purpose == "business" for acc in accounts)
    if has_personal and not feishu and not wecom:
        raise ValueError("个人邮箱已启用：请至少配置 FEISHU_WEBHOOK_URL 或 WECOM_WEBHOOK_URL")
    if has_business:
        if not business_feishu and not business_wecom:
            raise ValueError(
                "企业邮箱已启用：请至少配置 BUSINESS_FEISHU_WEBHOOK_URL "
                "或 BUSINESS_WECOM_WEBHOOK_URL"
            )
        if not os.getenv("BUSINESS_DEEPSEEK_API_KEY", "").strip():
            raise ValueError("企业邮箱已启用：请填写 BUSINESS_DEEPSEEK_API_KEY")

    try:
        poll_interval = int(os.getenv("POLL_INTERVAL_SEC", "1800"))
    except ValueError:
        poll_interval = 1800
    poll_interval = max(900, poll_interval)

    try:
        overquota_wait = int(os.getenv("IMAP_OVERQUOTA_WAIT_SEC", "10800"))
    except ValueError:
        overquota_wait = 10800
    overquota_wait = max(60, overquota_wait)

    try:
        heartbeat_stall_sec = int(os.getenv("HEARTBEAT_STALL_SEC", "7200"))
    except ValueError:
        heartbeat_stall_sec = 7200
    heartbeat_stall_sec = max(300, heartbeat_stall_sec)

    try:
        heartbeat_check_sec = int(os.getenv("HEARTBEAT_CHECK_SEC", "300"))
    except ValueError:
        heartbeat_check_sec = 300
    heartbeat_check_sec = max(60, heartbeat_check_sec)

    try:
        max_body = int(os.getenv("MAX_BODY_CHARS", "12000"))
    except ValueError:
        max_body = 12000
    max_body = max(1000, max_body)

    return AppConfig(
        deepseek_api_key=api_key,
        deepseek_base_url=os.getenv(
            "DEEPSEEK_BASE_URL", "https://api.deepseek.com"
        ).strip(),
        deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip(),
        business_deepseek_api_key=os.getenv(
            "BUSINESS_DEEPSEEK_API_KEY", ""
        ).strip(),
        business_deepseek_base_url=os.getenv(
            "BUSINESS_DEEPSEEK_BASE_URL",
            os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        ).strip(),
        business_deepseek_model=os.getenv(
            "BUSINESS_DEEPSEEK_MODEL",
            os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        ).strip(),
        accounts=accounts,
        feishu_webhook=feishu,
        wecom_webhook=wecom,
        business_feishu_webhook=business_feishu,
        business_wecom_webhook=business_wecom,
        poll_interval_sec=poll_interval,
        data_dir=data_dir,
        max_body_chars=max_body,
        filter_mode=_resolve_filter_mode(),
        notify_format=_resolve_notify_format(),
        daily_digest_enabled=_bool(os.getenv("DAILY_DIGEST_ENABLED")),
        daily_digest_time=_resolve_daily_digest_time(),
        process_existing_unread=_bool(os.getenv("PROCESS_EXISTING_UNREAD")),
        catchup_since_last_run=_bool(
            os.getenv("CATCHUP_SINCE_LAST_RUN"), default=True
        ),
        imap_use_idle=_bool(os.getenv("IMAP_USE_IDLE")),
        imap_overquota_wait_sec=overquota_wait,
        heartbeat_alert_enabled=_bool(
            os.getenv("HEARTBEAT_ALERT_ENABLED"), default=True
        ),
        heartbeat_stall_sec=heartbeat_stall_sec,
        heartbeat_check_sec=heartbeat_check_sec,
        forward_source_map=_parse_forward_source_map(),
    )
