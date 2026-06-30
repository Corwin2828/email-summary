from __future__ import annotations

import logging
from dataclasses import asdict, dataclass

import requests

from src.config import AppConfig
from src.email_parser import ParsedEmail

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SendResult:
    purpose: str
    channel: str
    ok: bool
    detail: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _channel_name(label: str) -> str:
    return "飞书" if label == "feishu" else "企业微信"


def _safe_error(exc: Exception, webhook: str) -> str:
    text = str(exc) or exc.__class__.__name__
    if webhook:
        text = text.replace(webhook, "[webhook已隐藏]")
    return text[:240]


def _send_text(webhook: str, text: str, label: str) -> None:
    if label == "feishu":
        payload = {"msg_type": "text", "content": {"text": text}}
    else:
        payload = {"msgtype": "text", "text": {"content": text}}

    resp = requests.post(webhook, json=payload, timeout=15)
    resp.raise_for_status()
    try:
        data = resp.json()
    except ValueError as e:
        raise RuntimeError(f"{label} 返回非 JSON: {resp.text[:200]}") from e

    if label == "feishu":
        if data.get("code") not in (0, None):
            raise RuntimeError(f"飞书返回错误: {data}")
    else:
        # 企业微信群机器人成功为 {"errcode":0,"errmsg":"ok"}。
        # 例如触发频率限制时会返回 errcode=45009（HTTP 仍可能是 200）。
        if data.get("errcode") not in (0, None):
            raise RuntimeError(f"企业微信返回错误: {data}")


def build_notification_template(email: ParsedEmail, summary: str) -> str:
    """本地模板拼装（NOTIFY_FORMAT=template 时使用）。"""
    author = email.original_sender or email.sender or "(未知发件人)"
    mailbox = email.forward_via or email.source_mailbox
    lines = [f"📬 新邮件总结 [{email.account}]", "━━━━━━━━━━━━━━"]
    if mailbox:
        lines.append(f"📨 转发自: {mailbox}")
    lines.append(f"✉️ 发件人: {author}")
    lines.append(f"📋 主题: {email.inner_subject or email.subject or '(无)'}")
    lines.append(f"时间: {email.date or '未知'}")
    lines.append("━━━━━━━━━━━━━━")
    lines.append(summary)
    return "\n".join(lines)


def _channels_for_purpose(config: AppConfig, purpose: str) -> list[tuple[str, str]]:
    if purpose == "business":
        channels: list[tuple[str, str]] = []
        if config.business_feishu_webhook:
            channels.append((config.business_feishu_webhook, "feishu"))
        if config.business_wecom_webhook:
            channels.append((config.business_wecom_webhook, "wecom"))
        return channels

    channels = []
    if config.feishu_webhook:
        channels.append((config.feishu_webhook, "feishu"))
    if config.wecom_webhook:
        channels.append((config.wecom_webhook, "wecom"))
    return channels


def _channels_for_all(config: AppConfig) -> list[tuple[str, str, str]]:
    channels: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for purpose in ("personal", "business"):
        for webhook, label in _channels_for_purpose(config, purpose):
            if webhook in seen:
                continue
            seen.add(webhook)
            channels.append((webhook, label, purpose))
    return channels


def send_text_all(config: AppConfig, text: str) -> list[SendResult]:
    """向所有已配置的 Webhook 发送管理类通知，返回逐渠道结果。"""
    results: list[SendResult] = []
    channels = _channels_for_all(config)
    if not channels:
        return [
            SendResult(
                purpose="all",
                channel="未配置",
                ok=False,
                detail="未配置任何通知渠道",
            )
        ]

    for webhook, label, purpose in channels:
        channel = _channel_name(label)
        try:
            _send_text(webhook, text, label)
            logger.info("已通过%s发送管理通知", channel)
            results.append(
                SendResult(
                    purpose=purpose,
                    channel=channel,
                    ok=True,
                    detail="已发送",
                )
            )
        except Exception as e:
            detail = _safe_error(e, webhook)
            logger.warning("%s管理通知发送失败: %s", channel, detail)
            results.append(
                SendResult(
                    purpose=purpose,
                    channel=channel,
                    ok=False,
                    detail=detail,
                )
            )
    return results


def send_text(config: AppConfig, text: str, purpose: str = "personal") -> None:
    """将文本原样推送到已配置的 Webhook。"""
    errors: list[str] = []
    sent = False

    for webhook, label in _channels_for_purpose(config, purpose):
        try:
            _send_text(webhook, text, label)
            logger.info("已通过%s发送", _channel_name(label))
            sent = True
        except Exception as e:
            channel = _channel_name(label)
            detail = _safe_error(e, webhook)
            logger.warning("%s发送失败: %s", channel, detail)
            errors.append(f"{channel}: {detail}")

    if not sent:
        raise RuntimeError("; ".join(errors) or "未配置通知渠道")


def send_summary(
    config: AppConfig,
    email: ParsedEmail,
    summary: str,
    purpose: str = "personal",
) -> None:
    """template 模式：本地套模板后发送。"""
    send_text(config, build_notification_template(email, summary), purpose)
