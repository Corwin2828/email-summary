from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from src.config import AppConfig
from src.deepseek_client import DeepSeekClient, format_skip_log
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

    def handle_raw(self, account: str, uid: str, raw: bytes) -> None:
        with self._lock:
            if self._store.seen(account, uid):
                return

            agg = self._aggregator_address(account)
            purpose = self._purpose_for_account(account)
            parsed = parse_raw_email(
                account,
                uid,
                raw,
                agg,
                self._config.forward_source_map,
            )

            if self._config.filter_mode == "ai":
                try:
                    keep = self._ai.should_keep_ai(parsed, agg)
                except Exception:
                    attempts = self._bump_attempt(account, uid)
                    logger.exception(
                        "AI 过滤失败 (%s/%s): %s",
                        attempts,
                        MAX_PROCESS_ATTEMPTS,
                        parsed.subject[:80],
                    )
                    if attempts >= MAX_PROCESS_ATTEMPTS:
                        logger.error(
                            "AI 过滤多次失败，跳过该邮件: %s",
                            parsed.subject[:80],
                        )
                        self._mark_done(account, uid)
                    return

                if not keep:
                    logger.info(
                        "[跳过] %s | ai | DeepSeek 判定无需总结 | %s",
                        account,
                        parsed.subject[:60],
                    )
                    self._mark_done(account, uid)
                    return
            else:
                fr = classify_email(parsed, verification_mode="strict")
                if not fr.should_summarize:
                    logger.info(format_skip_log(parsed, fr))
                    self._mark_done(account, uid)
                    return

            try:
                if self._config.notify_format == "ai":
                    message = self._ai.compose_notification(parsed, agg)
                else:
                    summary = self._ai.summarize(parsed)
                    message = None
            except Exception:
                attempts = self._bump_attempt(account, uid)
                logger.exception(
                    "AI 生成失败 (%s/%s): %s",
                    attempts,
                    MAX_PROCESS_ATTEMPTS,
                    parsed.subject[:80],
                )
                if attempts >= MAX_PROCESS_ATTEMPTS:
                    logger.error(
                        "已达最大重试次数，跳过该邮件: %s", parsed.subject[:80]
                    )
                    self._mark_done(account, uid)
                return

            try:
                if self._config.notify_format == "ai":
                    send_text(self._config, message or "", purpose)
                else:
                    send_summary(self._config, parsed, summary, purpose)  # type: ignore[name-defined]
            except Exception:
                attempts = self._bump_attempt(account, uid)
                logger.exception(
                    "通知发送失败 (%s/%s): %s",
                    attempts,
                    MAX_PROCESS_ATTEMPTS,
                    parsed.subject[:80],
                )
                if attempts >= MAX_PROCESS_ATTEMPTS:
                    logger.error(
                        "通知发送多次失败，跳过该邮件: %s",
                        parsed.subject[:80],
                    )
                    self._mark_done(account, uid)
                return

            self._clear_attempt(account, uid)
            self._mark_done(account, uid)
            logger.info("[已总结] %s | %s", account, parsed.subject[:80])
