from __future__ import annotations

import logging

from openai import OpenAI

from src.config import AppConfig
from src.email_parser import ParsedEmail
from src.filter_rules import FilterResult
from src.prompts import load_prompts

logger = logging.getLogger(__name__)


class DeepSeekClient:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._client = OpenAI(
            api_key=config.deepseek_api_key,
            base_url=config.deepseek_base_url,
        )

    def _chat(self, system: str, user: str) -> str:
        resp = self._client.chat.completions.create(
            model=self._config.deepseek_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.3,
            # 避免网络抖动时长时间卡死 worker，导致后续邮件都堆积不发送
            timeout=90,
        )
        if not resp.choices:
            raise RuntimeError("DeepSeek 返回为空 choices")
        content = resp.choices[0].message.content
        if not content:
            raise RuntimeError("DeepSeek 返回空内容")
        return content.strip()

    def _email_packet(
        self, email: ParsedEmail, aggregator_address: str = ""
    ) -> str:
        """把原始邮件信息交给模型自行理解，不做本地转发字段预判。"""
        body = email.body_text or ""
        if len(body) > self._config.max_body_chars:
            body = body[: self._config.max_body_chars] + "\n\n[正文已截断…]"

        lines = [
            f"监听账户名: {email.account}",
            f"汇总邮箱（IMAP 收件地址）: {aggregator_address or '(未配置)'}",
            f"邮件头 From: {email.sender or '(无)'}",
            f"邮件头 Subject: {email.subject or '(无)'}",
            f"邮件头 Date: {email.date or '(无)'}",
        ]
        if self._config.forward_source_map:
            lines.append("用户配置的邮箱别名（可选用）:")
            for addr, label in self._config.forward_source_map.items():
                lines.append(f"  {addr} → {label}")
        lines.append(f"\n正文:\n{body or '(无正文)'}")
        return "\n".join(lines)

    def should_keep_ai(
        self, email: ParsedEmail, aggregator_address: str = ""
    ) -> bool:
        prompts = load_prompts(self._config.data_dir)
        user = self._email_packet(email, aggregator_address)
        out = self._chat(prompts["filter_system"], user).upper()
        return out.startswith("KEEP")

    def compose_notification(
        self, email: ParsedEmail, aggregator_address: str = ""
    ) -> str:
        """由 DeepSeek 按 Prompt 规定格式生成整段推送文案。"""
        prompts = load_prompts(self._config.data_dir)
        system = prompts["summary_system"].replace("{account}", email.account)
        user = self._email_packet(email, aggregator_address)
        return self._chat(system, user)

    def summarize(self, email: ParsedEmail) -> str:
        """旧模式：仅返回总结正文（由本地模板拼装通知）。"""
        prompts = load_prompts(self._config.data_dir)
        body = email.body_text
        if len(body) > self._config.max_body_chars:
            body = body[: self._config.max_body_chars] + "\n\n[正文已截断…]"
        user = (
            f"邮箱账户: {email.account}\n"
            f"发件人: {email.original_sender or email.sender}\n"
            f"时间: {email.date}\n"
            f"主题: {email.inner_subject or email.subject}\n\n"
            f"正文:\n{body or '(无正文)'}"
        )
        legacy_prompt = (
            "你是邮件助理。请用简体中文 3-5 句话总结下列邮件正文，"
            "若有待办请列出。只输出总结正文，不要加标题。"
        )
        return self._chat(legacy_prompt, user)


def format_skip_log(email: ParsedEmail, fr: FilterResult) -> str:
    return (
        f"[跳过] {email.account} | {fr.reason.value} | {fr.detail} | "
        f"{email.subject[:60]}"
    )
