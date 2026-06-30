from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from src.config import AppConfig
from src.deepseek_client import DeepSeekClient, format_skip_log
from src.diagnostics import notify_system_issue
from src.email_parser import parse_raw_email
from src.filter_rules import classify_email
from src.notify import send_summary, send_text
from src.storage import ProcessedStore

logger = logging.getLogger(__name__)

MAX_PROCESS_ATTEMPTS = 3


class EmailPipeline:
    def __init__(
        self,
        config: AppConfig,
        store: ProcessedStore,
        on_activity: Callable[[str], None] | None = None,
    ) -> None:
        self._config = config
        self._store = store
        self._ai = DeepSeekClient(config)
        self._lock = threading.Lock()
        self._attempts: dict[tuple[str, str], int] = {}
        self._alerted_failures: set[tuple[str, str, str]] = set()
        self._on_activity = on_activity

    def _bump_attempt(self, account: str, uid: str) -> int:
        key = (account, uid)
        self._attempts[key] = self._attempts.get(key, 0) + 1
        return self._attempts[key]

    def _clear_attempt(self, account: str, uid: str) -> None:
        self._attempts.pop((account, uid), None)

    def _mark_done(self, account: str, uid: str) -> None:
        self._store.mark(account, uid)
        if self._on_activity:
            self._on_activity(account)

    def _aggregator_address(self, account: str) -> str:
        for acc in self._config.accounts:
            if acc.name == account:
                return acc.address
        return ""

    def _purpose_for_account(self, account: str) -> str:
        for acc in self._config.accounts:
            if acc.name == account:
                return acc.purpose
        return "personal"

    def _account_config(self, account: str):
        for acc in self._config.accounts:
            if acc.name == account:
                return acc
        return None

    def retry_delay_for(self, account: str) -> int:
        acc = self._account_config(account)
        if acc:
            return max(30, acc.retry_failed_after_sec)
        return 120

    def _business_fallback_message(self, parsed) -> str:
        body = parsed.body_text or ""
        if len(body) > 2500:
            body = body[:2500] + "\n\n[正文已截断，请登录邮箱查看完整原文]"
        author = parsed.original_sender or parsed.sender or "(未知发件人)"
        subject = parsed.inner_subject or parsed.subject or "(无主题)"
        return "\n".join(
            [
                "【AEBBS 询盘兜底通知】",
                "AI 总结或标准推送流程失败，但这封邮件可能是客户线索，已先推送原始信息。",
                "━━━━━━━━━━━━━━",
                f"账户: {parsed.account}",
                f"发件人: {author}",
                f"主题: {subject}",
                f"时间: {parsed.date or '未知'}",
                "━━━━━━━━━━━━━━",
                body or "(无正文)",
            ]
        )

    def _alert_processing_failure(
        self,
        account: str,
        uid: str,
        parsed,
        stage: str,
        attempts: int,
        exc: Exception,
    ) -> None:
        if attempts < MAX_PROCESS_ATTEMPTS:
            return
        key = (account, stage, str(exc)[:160])
        if key in self._alerted_failures:
            return
        self._alerted_failures.add(key)
        author = parsed.original_sender or parsed.sender or "(未知发件人)"
        subject = parsed.inner_subject or parsed.subject or "(无主题)"
        detail = "\n".join(
            [
                f"阶段: {stage}",
                f"账户: {account}",
                f"邮件 UID: {uid}",
                f"发件人: {author}",
                f"主题: {subject}",
                f"连续失败: {attempts} 次",
                f"错误: {str(exc)[:500]}",
                "该邮件未标记为已处理，后续会继续重试。",
            ]
        )
        try:
            notify_system_issue(self._config, "邮件处理连续失败", detail)
        except Exception:
            logger.exception("发送邮件处理失败告警失败")

    def _finish_business_with_fallback(self, account: str, uid: str, parsed) -> bool:
        try:
            send_text(
                self._config,
                self._business_fallback_message(parsed),
                "business",
            )
        except Exception:
            attempts = self._bump_attempt(account, uid)
            logger.exception(
                "AEBBS 兜底通知发送失败，保留未完成状态以便重试: %s",
                parsed.subject[:80],
            )
            self._alert_processing_failure(
                account,
                uid,
                parsed,
                "AEBBS 兜底通知发送",
                attempts,
                RuntimeError("AEBBS 兜底通知发送失败"),
            )
            return False
        self._clear_attempt(account, uid)
        self._mark_done(account, uid)
        logger.warning(
            "[AEBBS 兜底已推送] %s | %s",
            account,
            parsed.subject[:80],
        )
        return True

    def handle_raw(self, account: str, uid: str, raw: bytes) -> bool:
        with self._lock:
            if self._store.seen(account, uid):
                return True

            agg = self._aggregator_address(account)
            purpose = self._purpose_for_account(account)
            acc = self._account_config(account)
            parsed = parse_raw_email(
                account,
                uid,
                raw,
                agg,
                self._config.forward_source_map,
            )

            if purpose == "business" and acc and acc.bypass_filter:
                logger.info(
                    "[保留] %s | AEBBS 已绕过过滤，避免漏掉客户邮件 | %s",
                    account,
                    parsed.subject[:60],
                )
            elif self._config.filter_mode == "ai":
                try:
                    keep = self._ai.should_keep_ai(parsed, agg)
                except Exception as e:
                    attempts = self._bump_attempt(account, uid)
                    logger.exception(
                        "AI 过滤失败（第 %s 次）: %s",
                        attempts,
                        parsed.subject[:80],
                    )
                    if purpose == "business":
                        return self._finish_business_with_fallback(
                            account, uid, parsed
                        )
                    if attempts >= MAX_PROCESS_ATTEMPTS:
                        logger.warning(
                            "AI 过滤多次失败，继续保留该邮件等待重试: %s",
                            parsed.subject[:80],
                        )
                    self._alert_processing_failure(
                        account,
                        uid,
                        parsed,
                        "AI 过滤",
                        attempts,
                        e,
                    )
                    return False

                if not keep:
                    logger.info(
                        "[跳过] %s | ai | DeepSeek 判定无需总结 | %s",
                        account,
                        parsed.subject[:60],
                    )
                    self._mark_done(account, uid)
                    return True
            else:
                fr = classify_email(parsed, verification_mode="strict")
                if not fr.should_summarize:
                    logger.info(format_skip_log(parsed, fr))
                    self._mark_done(account, uid)
                    return True

            try:
                if self._config.notify_format == "ai":
                    message = self._ai.compose_notification(parsed, agg)
                else:
                    summary = self._ai.summarize(parsed)
                    message = None
            except Exception as e:
                attempts = self._bump_attempt(account, uid)
                logger.exception(
                    "AI 生成失败（第 %s 次）: %s",
                    attempts,
                    parsed.subject[:80],
                )
                if purpose == "business":
                    return self._finish_business_with_fallback(
                        account, uid, parsed
                    )
                if attempts >= MAX_PROCESS_ATTEMPTS:
                    logger.warning(
                        "AI 生成多次失败，继续保留该邮件等待重试: %s",
                        parsed.subject[:80],
                    )
                self._alert_processing_failure(
                    account,
                    uid,
                    parsed,
                    "AI 生成通知",
                    attempts,
                    e,
                )
                return False

            try:
                if self._config.notify_format == "ai":
                    send_text(self._config, message or "", purpose)
                else:
                    send_summary(self._config, parsed, summary, purpose)  # type: ignore[name-defined]
            except Exception as e:
                attempts = self._bump_attempt(account, uid)
                logger.exception(
                    "通知发送失败（第 %s 次）: %s",
                    attempts,
                    parsed.subject[:80],
                )
                if purpose == "business":
                    return self._finish_business_with_fallback(
                        account, uid, parsed
                    )
                if attempts >= MAX_PROCESS_ATTEMPTS:
                    logger.warning(
                        "通知发送多次失败，继续保留该邮件等待重试: %s",
                        parsed.subject[:80],
                    )
                self._alert_processing_failure(
                    account,
                    uid,
                    parsed,
                    "Webhook 通知发送",
                    attempts,
                    e,
                )
                return False

            self._clear_attempt(account, uid)
            self._mark_done(account, uid)
            logger.info("[已总结] %s | %s", account, parsed.subject[:80])
            return True
