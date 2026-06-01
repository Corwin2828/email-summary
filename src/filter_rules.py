from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from src.email_parser import ParsedEmail


class FilterReason(str, Enum):
    PASS = "pass"
    VERIFICATION = "verification"
    MARKETING = "marketing"
    SUBSCRIPTION = "subscription"
    AUTOMATED = "automated"
    LOW_VALUE = "low_value"


@dataclass
class FilterResult:
    should_summarize: bool
    reason: FilterReason
    detail: str


_VERIFICATION = re.compile(
    r"(验证码|校验码|校验号码|动态码|动态密码|一次性密码|一次性验证码|"
    r"安全码|安全代码|登录码|授权码|确认码|激活码|"
    r"\bOTP\b|passcode|verification\s*code|security\s*code|"
    r"confirm\s*your\s*email|登录验证|身份验证|"
    r"sign[- ]?in\s*code|two[- ]?factor|\b2fa\b|\bmfa\b|"
    r"your\s+(code|pin)\s+is|code\s+is|验证码为|验证码：|"
    r"enter\s+(the\s+)?code|输入验证码|请输入验证码)",
    re.I,
)

_MARKETING_SUBJECT = re.compile(
    r"(促销|特惠|折扣|优惠券|限时|清仓|大促|双11|黑五|"
    r"sale\b|discount|promo(tion)?|newsletter|"
    r"unsubscribe|营销|广告|% off|free shipping)",
    re.I,
)

_SUBSCRIPTION_SUBJECT = re.compile(
    r"(订阅|周报|月报|digest|weekly\s*update|"
    r"your\s*daily|roundup|简报|通讯)",
    re.I,
)

_NO_REPLY = re.compile(
    r"(noreply|no-reply|donotreply|do-not-reply|"
    r"mailer-daemon|notification@|notifications@|"
    r"news@|newsletter@|marketing@|promo@|"
    r"bounce@|automated@|account-security|security-noreply)",
    re.I,
)

_MARKETING_DOMAINS = (
    "mailchimp.com",
    "sendgrid.net",
    "constantcontact.com",
    "substack.com",
    "beehiiv.com",
    "campaign-archive.com",
    "list-manage.com",
    "emltrk.com",
    "click.discord.com",
)

# 同行须出现验证码相关词 + 数字，避免「正文里单独一行数字」误伤（如引用上一封邮件）
_CODE_HEAVY_BODY = re.compile(
    r"(?:验证码|校验码|安全码|安全代码|动态码|一次性密码|"
    r"verification\s*code|security\s*code|passcode|\bOTP\b|one[- ]time)"
    r"[^\d\n]{0,60}[\d\s]{4,10}\b|"
    r"\b[\d\s]{4,10}[^\d\n]{0,60}(?:验证码|校验码|安全码)",
    re.I,
)

# 回复/转发引用块起始（引用内验证码不应影响当前邮件）
_REPLY_SPLIT = re.compile(
    r"(?:^|\n)(?:"
    r"On .+?wrote:\s*|"
    r"在 .+?写道：\s*|"
    r"-{5,}\s*Original Message\s*-+|"
    r"-{5,}\s*Forwarded message\s*-+"
    r")",
    re.I | re.M,
)


def _visible_body(body: str) -> str:
    """去掉回复引用块，只对用户新写内容做验证码启发式判断。"""
    if not body:
        return ""
    m = _REPLY_SPLIT.search(body)
    if m:
        body = body[: m.start()]
    kept: list[str] = []
    for line in body.splitlines():
        if line.lstrip().startswith(">"):
            break
        kept.append(line)
    return "\n".join(kept).strip()


def _filter_text(email: ParsedEmail) -> str:
    """合并主题、内嵌主题与全文，避免转发邮件漏检（验证码常在转发块之后）。"""
    body = email.body_text or ""
    if not email.is_forwarded:
        body = _visible_body(body)
    parts = [
        email.subject or "",
        email.inner_subject or "",
        email.sender or "",
        body,
    ]
    return "\n".join(p for p in parts if p)


def _verification_text(email: ParsedEmail) -> str:
    """验证码规则只看主题/内嵌主题与用户新写正文；非转发不含引用块。"""
    parts = [email.subject or "", email.inner_subject or ""]
    body = email.body_text or ""
    if email.is_forwarded:
        parts.append(body)
    else:
        parts.append(_visible_body(body))
    return "\n".join(p for p in parts if p)


def _sender_lower(email: ParsedEmail) -> str:
    return (email.original_sender or email.sender or "").lower()


def classify_email(
    email: ParsedEmail, *, verification_mode: str = "strict"
) -> FilterResult:
    subject = email.subject or ""
    inner = email.inner_subject or ""
    sender = _sender_lower(email)
    full_text = _filter_text(email)
    full_lower = full_text.lower()
    use_ai_for_otp = verification_mode.strip().lower() == "ai"
    raw_body = (email.body_text or "").strip()
    body_stripped = raw_body if email.is_forwarded else _visible_body(raw_body)

    if not use_ai_for_otp:
        otp_text = _verification_text(email)
        otp_lower = otp_text.lower()

        if _VERIFICATION.search(subject) or _VERIFICATION.search(inner):
            return FilterResult(
                False, FilterReason.VERIFICATION, "主题含验证码/安全码关键词"
            )

        if _VERIFICATION.search(otp_lower):
            return FilterResult(
                False, FilterReason.VERIFICATION, "正文含验证码/安全码关键词"
            )

        if len(body_stripped) < 120 and _CODE_HEAVY_BODY.search(body_stripped):
            return FilterResult(
                False, FilterReason.VERIFICATION, "短内容数字验证码邮件"
            )

    if _MARKETING_SUBJECT.search(subject) or _MARKETING_SUBJECT.search(inner):
        return FilterResult(
            False, FilterReason.MARKETING, "主题含营销/促销关键词"
        )

    if _SUBSCRIPTION_SUBJECT.search(subject) or _SUBSCRIPTION_SUBJECT.search(
        inner
    ):
        return FilterResult(
            False, FilterReason.SUBSCRIPTION, "主题含订阅/简报关键词"
        )

    for domain in _MARKETING_DOMAINS:
        if domain in sender:
            return FilterResult(
                False, FilterReason.MARKETING, f"发件域为常见营销平台: {domain}"
            )

    if _NO_REPLY.search(sender) and (
        _MARKETING_SUBJECT.search(full_lower)
        or _SUBSCRIPTION_SUBJECT.search(full_lower)
        or "unsubscribe" in full_lower
        or "退订" in full_lower
    ):
        return FilterResult(
            False, FilterReason.AUTOMATED, "自动发送且含营销/退订特征"
        )

    if "unsubscribe" in full_lower or "退订" in full_lower:
        if _MARKETING_SUBJECT.search(full_lower) or _SUBSCRIPTION_SUBJECT.search(
            full_lower
        ):
            return FilterResult(
                False, FilterReason.SUBSCRIPTION, "含退订链接的订阅/营销邮件"
            )

    if ("unsubscribe" in full_lower or "退订" in full_lower) and len(
        body_stripped
    ) < 400:
        if not re.search(
            r"(请回复|please reply|action required|待办|urgent)", subject, re.I
        ):
            return FilterResult(
                False, FilterReason.LOW_VALUE, "短营销/订阅模板邮件"
            )

    return FilterResult(True, FilterReason.PASS, "通过规则过滤")
