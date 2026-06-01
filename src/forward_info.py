from __future__ import annotations

import re
from dataclasses import dataclass
from email.header import decode_header
from email.message import Message
from email.utils import getaddresses

# Gmail / Outlook / Apple 常见转发标记
_FORWARD_MARKERS = re.compile(
    r"(----------\s*Forwarded message\s*----------|"
    r"----------\s*转发的邮件\s*----------|"
    r"--------\s*转发的邮件\s*--------|"
    r"Begin forwarded message:|"
    r"_{5,}\s*Forwarded message|"
    r"转发邮件[：:]?\s*$)",
    re.I | re.M,
)

_FROM_LINE = re.compile(
    r"^(?:From|发件人|De|Von|从)\s*[:：]\s*(.+)$",
    re.I | re.M,
)

_TO_LINE = re.compile(
    r"^(?:To|收件人|送达|An|À)\s*[:：]\s*(.+)$",
    re.I | re.M,
)

_SUBJECT_LINE = re.compile(
    r"^(?:Subject|主题|Betreff|Objet)\s*[:：]\s*(.+)$",
    re.I | re.M,
)

_EMAIL_IN_ANGLE = re.compile(r"<([^>]+@[^>]+)>")
_EMAIL_PLAIN = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+", re.I)

# 可能标明「原收件人 / 转发目标」的邮件头
_SOURCE_MAILBOX_HEADERS = (
    "X-Original-To",
    "X-Forwarded-To",
    "X-Gm-Original-To",
    "X-MS-Exchange-Organization-OriginalEnvelopeRecipient",
    "Delivered-To",
    "X-Envelope-To",
)

_ORIGINAL_FROM_HEADERS = (
    "X-Google-Original-From",
    "X-Original-From",
    "X-Forwarded-From",
    "Resent-From",
    "X-Original-Sender",
)


@dataclass
class ForwardInfo:
    is_forwarded: bool
    original_from: str
    source_mailbox: str
    source_mailbox_display: str
    inner_subject: str


def _decode_header_value(value: str | None) -> str:
    if not value:
        return ""
    parts: list[str] = []
    for fragment, charset in decode_header(value):
        if isinstance(fragment, bytes):
            parts.append(fragment.decode(charset or "utf-8", errors="replace"))
        else:
            parts.append(fragment)
    return "".join(parts).strip()


def _extract_email(addr: str) -> str:
    if not addr:
        return ""
    m = _EMAIL_IN_ANGLE.search(addr)
    if m:
        return m.group(1).lower()
    m2 = _EMAIL_PLAIN.search(addr)
    return m2.group(0).lower() if m2 else ""


def _extract_emails_from_header(value: str | None) -> list[str]:
    if not value:
        return []
    decoded = _decode_header_value(value)
    return [a.lower() for _, a in getaddresses([decoded]) if a and "@" in a]


def _format_mailbox_display(
    address: str,
    source_map: dict[str, str] | None,
) -> str:
    if not address:
        return ""
    addr = address.lower()
    if source_map and addr in source_map:
        return f"{source_map[addr]} <{address}>"
    return address


def _is_aggregator(address: str, aggregator_address: str) -> bool:
    if not address or not aggregator_address:
        return False
    return address.lower() == aggregator_address.lower()


def _pick_source_mailbox(
    candidates: list[str],
    aggregator_address: str,
    source_map: dict[str, str] | None,
) -> str:
    """从候选地址中选出「用户被转发前的收件邮箱」，排除汇总 Gmail。"""
    seen: set[str] = set()
    ordered: list[str] = []
    for c in candidates:
        addr = _extract_email(c) or c.lower()
        if not addr or addr in seen:
            continue
        seen.add(addr)
        ordered.append(addr)

    if source_map:
        for addr in ordered:
            if addr in source_map and not _is_aggregator(addr, aggregator_address):
                return addr

    for addr in ordered:
        if not _is_aggregator(addr, aggregator_address):
            return addr
    return ""


def _parse_forward_block(body_text: str) -> tuple[str, str, str]:
    """从正文转发块解析：发件人、原收件邮箱、内嵌主题。"""
    marker = _FORWARD_MARKERS.search(body_text)
    if not marker:
        return "", "", ""
    block = body_text[marker.end() : marker.end() + 4000]

    original_from = ""
    original_to = ""
    inner_subject = ""

    fm = _FROM_LINE.search(block)
    if fm:
        original_from = fm.group(1).strip()

    tm = _TO_LINE.search(block)
    if tm:
        original_to = tm.group(1).strip()

    sm = _SUBJECT_LINE.search(block)
    if sm:
        inner_subject = sm.group(1).strip()

    return original_from, original_to, inner_subject


def _headers_source_mailbox(msg: Message, aggregator_address: str) -> list[str]:
    candidates: list[str] = []
    for name in _SOURCE_MAILBOX_HEADERS:
        for val in msg.get_all(name) or []:
            candidates.extend(_extract_emails_from_header(val))
    for name in ("To", "Cc", "Delivered-To"):
        for val in msg.get_all(name) or []:
            candidates.extend(_extract_emails_from_header(val))
    return [
        c
        for c in candidates
        if not _is_aggregator(c, aggregator_address)
    ]


def _headers_original_from(msg: Message) -> str:
    for name in _ORIGINAL_FROM_HEADERS:
        val = msg.get(name)
        if val:
            return _decode_header_value(val)
    return ""


def _detect_forwarded_by_subject(subject: str) -> bool:
    return bool(re.match(r"^(fwd?|fw|转发)\s*[:：]", subject or "", re.I))


def _strip_fwd_prefix(subject: str) -> str:
    return re.sub(r"^(fwd?|fw|转发)\s*[:：]\s*", "", subject or "", flags=re.I).strip()


def parse_forward_info(
    msg: Message,
    body_text: str,
    envelope_from: str,
    envelope_subject: str,
    aggregator_address: str = "",
    source_map: dict[str, str] | None = None,
) -> ForwardInfo:
    """
    解析转发/自动转发邮件。

    - original_from: 真正写这封信的人/系统（转发块里的 From，或信封 From）
    - source_mailbox: 用户哪个邮箱收到后被转到汇总邮箱（转发块里的 To，或邮件头）
    """
    body_forwarded = bool(_FORWARD_MARKERS.search(body_text[:8000]))
    headers_forwarded = bool(
        msg.get("Resent-From")
        or msg.get("X-Original-From")
        or msg.get("X-Google-Original-From")
    )
    subject_forwarded = _detect_forwarded_by_subject(envelope_subject)

    block_from, block_to, inner_subject = _parse_forward_block(body_text)

    header_from = _headers_original_from(msg)
    original_from = block_from or header_from

    mailbox_candidates: list[str] = []
    if block_to:
        mailbox_candidates.append(block_to)
    mailbox_candidates.extend(_headers_source_mailbox(msg, aggregator_address))
    if source_map:
        mailbox_candidates.extend(source_map.keys())

    source_mailbox = _pick_source_mailbox(
        mailbox_candidates, aggregator_address, source_map
    )

    is_forwarded = (
        body_forwarded
        or headers_forwarded
        or subject_forwarded
        or bool(source_mailbox and aggregator_address)
        or bool(block_from)
    )

    # 无转发块时：信封 From 通常就是真实发件人（自动转发不会改 From）
    if not original_from:
        original_from = envelope_from

    display = _format_mailbox_display(source_mailbox, source_map)

    if not inner_subject and subject_forwarded:
        inner_subject = _strip_fwd_prefix(envelope_subject)

    return ForwardInfo(
        is_forwarded=is_forwarded,
        original_from=original_from.strip(),
        source_mailbox=source_mailbox,
        source_mailbox_display=display,
        inner_subject=inner_subject.strip(),
    )
