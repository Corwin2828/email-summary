from __future__ import annotations

import email
import re
from dataclasses import dataclass
from email.header import decode_header
from email.message import Message
from typing import Any

import html2text

from src.forward_info import parse_forward_info, _extract_email


@dataclass
class ParsedEmail:
    account: str
    uid: str
    subject: str
    sender: str
    date: str
    body_text: str
    is_forwarded: bool = False
    """真正写这封信的人/系统（不是「从哪个邮箱转来的」）。"""
    original_sender: str = ""
    """用户被转发前的收件邮箱地址，如 corwincc@outlook.com。"""
    source_mailbox: str = ""
    """用于通知展示：优先自定义名，否则为 source_mailbox 地址。"""
    forward_via: str = ""
    inner_subject: str = ""


def _decode_header_value(value: str | None) -> str:
    if not value:
        return ""
    parts: list[str] = []
    for fragment, charset in decode_header(value):
        if isinstance(fragment, bytes):
            parts.append(
                fragment.decode(charset or "utf-8", errors="replace")
            )
        else:
            parts.append(fragment)
    return "".join(parts).strip()


def _html_to_text(html: str) -> str:
    converter = html2text.HTML2Text()
    converter.ignore_links = False
    converter.ignore_images = True
    converter.body_width = 0
    return converter.handle(html).strip()


def _decode_part_payload(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if not payload:
        return ""
    charset = part.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace")


def _extract_body(msg: Message) -> str:
    plain_parts: list[str] = []
    html_parts: list[str] = []

    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition", ""))
            if "attachment" in disp.lower():
                continue
            if ctype == "text/plain":
                text = _decode_part_payload(part).strip()
                if text:
                    plain_parts.append(text)
            elif ctype == "text/html":
                raw = _decode_part_payload(part)
                if raw:
                    html_parts.append(_html_to_text(raw))
    else:
        raw = _decode_part_payload(msg)
        if raw:
            if msg.get_content_type() == "text/html":
                html_parts.append(_html_to_text(raw))
            else:
                plain_parts.append(raw.strip())

    if plain_parts:
        combined = "\n\n".join(plain_parts)
    elif html_parts:
        combined = "\n\n".join(html_parts)
    else:
        combined = ""

    combined = re.sub(r"\n{3,}", "\n\n", combined)
    return combined.strip()


def _resolve_original_sender(
    msg: Message,
    envelope_from: str,
    parsed_from: str,
    aggregator_address: str,
) -> str:
    """发件人：优先转发块/原信 From，其次 Reply-To，最后信封 From。"""
    candidate = (parsed_from or "").strip() or envelope_from
    reply_to = _decode_header_value(msg.get("Reply-To"))
    if reply_to:
        rt_addr = _extract_email(reply_to)
        env_addr = _extract_email(envelope_from)
        if parsed_from:
            return candidate
        if aggregator_address and env_addr == aggregator_address.lower():
            return reply_to
        if not candidate or env_addr == aggregator_address.lower():
            return reply_to
    return candidate


def parse_raw_email(
    account: str,
    uid: str,
    raw: bytes | Any,
    aggregator_address: str = "",
    forward_source_map: dict[str, str] | None = None,
) -> ParsedEmail:
    msg = email.message_from_bytes(raw)
    subject = _decode_header_value(msg.get("Subject"))
    sender = _decode_header_value(msg.get("From"))
    body_text = _extract_body(msg)

    fwd = parse_forward_info(
        msg,
        body_text,
        sender,
        subject,
        aggregator_address,
        forward_source_map,
    )

    original_sender = _resolve_original_sender(
        msg, sender, fwd.original_from, aggregator_address
    )

    forward_display = fwd.source_mailbox_display or fwd.source_mailbox

    return ParsedEmail(
        account=account,
        uid=uid,
        subject=subject,
        sender=sender,
        date=_decode_header_value(msg.get("Date")),
        body_text=body_text,
        is_forwarded=fwd.is_forwarded,
        original_sender=original_sender,
        source_mailbox=fwd.source_mailbox,
        forward_via=forward_display,
        inner_subject=fwd.inner_subject,
    )
