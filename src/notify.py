from __future__ import annotations

import logging

import requests

from src.config import AppConfig
from src.email_parser import ParsedEmail

logger = logging.getLogger(__name__)


def _send_text(webhook: str, text: str, label: str) -> None:
    if label == "feishu":
        payload = {"msg_type": "text", "content": {"text": text}}
    else:
        payload = {"msgtype": "text", "text": {"content": text}}

    resp = requests.post(webhook, json=payload, timeout=15)
    resp.raise_for_status()
    if label == "feishu":
        try:
            data = resp.json()
        except ValueError as e:
            raise RuntimeError(f"飞书返回非 JSON: {resp.text[:200]}") from e
        if data.get("code") not in (0, None):
            raise RuntimeError(f"飞书返回错误: {data}")


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


def send_text(config: AppConfig, text: str) -> None:
    """将文本原样推送到已配置的 Webhook。"""
    errors: list[str] = []
    sent = False

    if config.feishu_webhook:
        try:
            _send_text(config.feishu_webhook, text, "feishu")
            logger.info("已通过飞书发送")
            sent = True
        except Exception as e:
            errors.append(f"飞书: {e}")

    if config.wecom_webhook:
        try:
            _send_text(config.wecom_webhook, text, "wecom")
            logger.info("已通过企业微信发送")
            sent = True
        except Exception as e:
            errors.append(f"企业微信: {e}")

    if not sent:
        raise RuntimeError("; ".join(errors) or "未配置通知渠道")


def send_summary(config: AppConfig, email: ParsedEmail, summary: str) -> None:
    """template 模式：本地套模板后发送。"""
    send_text(config, build_notification_template(email, summary))
