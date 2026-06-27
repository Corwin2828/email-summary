from __future__ import annotations

import logging
import ssl
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from imapclient import IMAPClient

from src.app_state import load_last_active_at, save_last_active_at
from src.config import AccountConfig

logger = logging.getLogger(__name__)

MAX_FETCH_PER_POLL = 20
QUIET_TZ = ZoneInfo("Asia/Shanghai")  # 东八区
QUIET_START_HOUR = 0  # 00:00
QUIET_END_HOUR = 7  # 07:00（不含）


def _is_overquota_error(exc: BaseException) -> bool:
    text = str(exc).upper()
    return "OVERQUOTA" in text or "BANDWIDTH LIMITS" in text


def _retry_wait_sec(
    exc: BaseException, normal_sec: int, overquota_sec: int
) -> int:
    return overquota_sec if _is_overquota_error(exc) else normal_sec


def _quiet_sleep_seconds(now: datetime) -> int:
    """东八区 00:00-07:00 不轮询，返回需等待秒数。"""
    local = now.astimezone(QUIET_TZ)
    if not (QUIET_START_HOUR <= local.hour < QUIET_END_HOUR):
        return 0
    resume = local.replace(
        hour=QUIET_END_HOUR, minute=0, second=0, microsecond=0
    )
    wait = int((resume - local).total_seconds())
    return max(wait, 1)


class ImapWatcher:
    def __init__(
        self,
        account: AccountConfig,
        on_message: Callable[[str, bytes], None],
        data_dir: Path,
        idle_timeout_sec: int = 540,
        process_existing_unread: bool = False,
        catchup_since_last_run: bool = True,
        use_idle: bool = False,
        overquota_wait_sec: int = 10800,
        quiet_hours_enabled: bool = True,
    ) -> None:
        self._account = account
        self._on_message = on_message
        self._data_dir = data_dir
        self._idle_timeout = idle_timeout_sec
        self._process_existing_unread = process_existing_unread
        self._catchup_since_last_run = catchup_since_last_run
        self._use_idle = use_idle
        self._overquota_wait_sec = max(60, overquota_wait_sec)
        self._quiet_hours_enabled = quiet_hours_enabled
        self._runtime_baseline: set[str] | None = None
        self._catchup_done = False
        self._submitted_uids: set[str] = set()
        self._client: IMAPClient | None = None
        self._consecutive_failures = 0
        self._on_error: Callable[[str, Exception, int], None] | None = None

    def set_error_callback(
        self, callback: Callable[[str, Exception, int], None] | None
    ) -> None:
        """设置错误回调：account_name, exc, failure_count。"""
        self._on_error = callback

    def _emit(self, uid: str, raw: bytes) -> None:
        if uid in self._submitted_uids:
            return
        self._submitted_uids.add(uid)
        self._on_message(uid, raw)

    @property
    def account_name(self) -> str:
        return self._account.name

    def _connect(self) -> IMAPClient:
        ctx = ssl.create_default_context()
        client = IMAPClient(
            self._account.host,
            port=self._account.port,
            ssl_context=ctx,
        )
        if self._account.use_oauth:
            from src.outlook_oauth import get_access_token

            token = get_access_token(
                self._account.address,
                self._account.azure_client_id,
                self._account.token_cache_path,  # type: ignore[arg-type]
            )
            client.oauth2_login(self._account.address, token)
        else:
            client.login(self._account.address, self._account.password)
        client.select_folder("INBOX", readonly=True)
        logger.info(
            "已连接 %s (%s)", self._account.name, self._account.address
        )
        return client

    def _ensure_client(self) -> IMAPClient:
        if self._client is not None:
            try:
                self._client.noop()
                return self._client
            except Exception:
                self._disconnect()
        self._client = self._connect()
        return self._client

    def _disconnect(self) -> None:
        if self._client is not None:
            try:
                self._client.logout()
            except Exception:
                pass
            self._client = None

    def close(self) -> None:
        self._disconnect()

    def _uids_since(self, client: IMAPClient, since: datetime) -> list[int]:
        """按 INTERNALDATE 筛选 since 之后收到的邮件。"""
        since_utc = since.astimezone(timezone.utc)
        search_from = (since_utc - timedelta(days=1)).date()
        uids = client.search(["SINCE", search_from])
        if not uids:
            return []

        fetched = client.fetch(uids, ["INTERNALDATE"])
        result: list[int] = []
        for uid, data in fetched.items():
            internal = data.get(b"INTERNALDATE")
            if internal is None:
                continue
            if internal.tzinfo is None:
                internal = internal.replace(tzinfo=timezone.utc)
            if internal.astimezone(timezone.utc) > since_utc:
                result.append(int(uid))
        return sorted(result)

    def _fetch_uids(self, client: IMAPClient, uids: list[int]) -> list[tuple[str, bytes]]:
        if not uids:
            return []
        if len(uids) > MAX_FETCH_PER_POLL:
            logger.info(
                "%s 本轮处理 %d/%d 封（其余下轮继续）",
                self._account.name,
                MAX_FETCH_PER_POLL,
                len(uids),
            )
            uids = uids[:MAX_FETCH_PER_POLL]

        result: list[tuple[str, bytes]] = []
        fetched = client.fetch(uids, ["RFC822"])
        for uid, data in fetched.items():
            raw = data.get(b"RFC822")
            if raw:
                result.append((str(uid), raw))
        return result

    def _establish_runtime_baseline(self, client: IMAPClient) -> None:
        """补发结束后快照当前未读，运行期间只处理新出现的未读。"""
        if self._runtime_baseline is not None:
            return
        if self._process_existing_unread:
            self._runtime_baseline = set()
            return
        unseen = client.search(["UNSEEN"])
        self._runtime_baseline = {str(u) for u in unseen}

    def _uids_for_live_poll(self, client: IMAPClient) -> list[int]:
        """运行期间：新未读（不在补发结束时的快照里）。"""
        self._establish_runtime_baseline(client)
        unseen = client.search(["UNSEEN"])
        if not unseen:
            return []
        if self._process_existing_unread:
            return list(unseen)
        baseline = self._runtime_baseline or set()
        return [u for u in unseen if str(u) not in baseline]

    def _run_startup_catchup(self, client: IMAPClient) -> None:
        if self._catchup_done or not self._catchup_since_last_run:
            self._catchup_done = True
            return
        if self._process_existing_unread:
            self._catchup_done = True
            return

        last = load_last_active_at(self._data_dir, self._account.name)
        if last is None:
            save_last_active_at(self._data_dir, account=self._account.name)
            logger.info(
                "%s 首次运行：不补发历史邮件，已记录起点时间",
                self._account.name,
            )
            self._catchup_done = True
            return

        logger.info(
            "%s 补发自上次关闭以来的邮件（自 %s 起）…",
            self._account.name,
            last.astimezone().strftime("%Y-%m-%d %H:%M"),
        )
        total = 0
        while True:
            uids = self._uids_since(client, last)
            uids = [u for u in uids if str(u) not in self._submitted_uids]
            if not uids:
                break
            batch = self._fetch_uids(client, uids)
            total += len(batch)
            for uid, raw in batch:
                self._emit(uid, raw)
            if len(uids) <= MAX_FETCH_PER_POLL:
                break

        if total:
            logger.info(
                "%s 已提交 %d 封补发总结（过滤规则仍生效，请稍候推送）",
                self._account.name,
                total,
            )
        else:
            logger.info("%s 上次关闭以来无新邮件需补发", self._account.name)

        self._catchup_done = True

    def fetch_pending(self) -> list[tuple[str, bytes]]:
        client = self._ensure_client()

        if not self._catchup_done:
            self._run_startup_catchup(client)
            self._establish_runtime_baseline(client)

        if self._process_existing_unread and self._catchup_done:
            uids = list(client.search(["UNSEEN"]))
        else:
            uids = self._uids_for_live_poll(client)

        result = self._fetch_uids(client, uids)
        # 成功拉取（即使本轮没有新邮件）视为连接正常，重置连续失败计数
        self._consecutive_failures = 0
        return result

    def _log_retry(self, exc: Exception, wait_sec: int, context: str) -> None:
        if _is_overquota_error(exc):
            if wait_sec >= 3600:
                wait_label = f"约 {max(1, wait_sec // 3600)} 小时后"
            else:
                wait_label = f"约 {max(1, wait_sec // 60)} 分钟后"
            logger.warning(
                "%s %s：Gmail 限流 (OVERQUOTA)，%s重试: %s",
                self._account.name,
                context,
                wait_label,
                exc,
            )
        else:
            logger.warning(
                "%s %s：%ss 后重试: %s",
                self._account.name,
                context,
                wait_sec,
                exc,
            )

    def _record_failure(self, exc: Exception) -> None:
        self._consecutive_failures += 1
        if self._on_error and self._consecutive_failures >= 3:
            # 只在第 3、6、9... 次时通知，避免刷屏
            if self._consecutive_failures % 3 == 0:
                try:
                    self._on_error(self.account_name, exc, self._consecutive_failures)
                except Exception:
                    logger.exception("错误回调执行失败")

    def run_poll_forever(self, poll_interval_sec: int) -> None:
        while True:
            quiet_wait = (
                _quiet_sleep_seconds(datetime.now(timezone.utc))
                if self._quiet_hours_enabled
                else 0
            )
            if quiet_wait > 0:
                mins = max(1, quiet_wait // 60)
                logger.info(
                    "%s 东八区静默时段（00:00-07:00），%d 分钟后恢复轮询",
                    self._account.name,
                    mins,
                )
                time.sleep(quiet_wait)
                continue

            wait_sec = poll_interval_sec
            try:
                batch = self.fetch_pending()
                if batch:
                    logger.info(
                        "%s 发现 %d 封待处理邮件",
                        self._account.name,
                        len(batch),
                    )
                for uid, raw in batch:
                    self._emit(uid, raw)
            except Exception as e:
                wait_sec = _retry_wait_sec(
                    e, poll_interval_sec, self._overquota_wait_sec
                )
                self._log_retry(e, wait_sec, "轮询失败")
                self._record_failure(e)
                self._disconnect()
            time.sleep(wait_sec)

    def run_forever(self, poll_fallback_sec: int) -> None:
        if not self._use_idle:
            self.run_poll_forever(poll_fallback_sec)
            return

        while True:
            quiet_wait = (
                _quiet_sleep_seconds(datetime.now(timezone.utc))
                if self._quiet_hours_enabled
                else 0
            )
            if quiet_wait > 0:
                mins = max(1, quiet_wait // 60)
                logger.info(
                    "%s 东八区静默时段（00:00-07:00），%d 分钟后恢复轮询",
                    self._account.name,
                    mins,
                )
                time.sleep(quiet_wait)
                continue

            try:
                while True:
                    try:
                        client = self._ensure_client()
                        if not self._catchup_done:
                            self._run_startup_catchup(client)
                            self._establish_runtime_baseline(client)

                        client.idle()
                        client.idle_check(timeout=self._idle_timeout)
                        client.idle_done()

                        for uid, raw in self.fetch_pending():
                            self._emit(uid, raw)

                    except Exception as e:
                        wait_sec = _retry_wait_sec(
                            e,
                            min(poll_fallback_sec, 30),
                            self._overquota_wait_sec,
                        )
                        self._log_retry(e, wait_sec, "IDLE 中断")
                        self._record_failure(e)
                        self._disconnect()
                        time.sleep(wait_sec)
                        break

            except Exception as e:
                wait_sec = _retry_wait_sec(
                    e, poll_fallback_sec, self._overquota_wait_sec
                )
                self._log_retry(e, wait_sec, "连接失败")
                self._record_failure(e)
                self._disconnect()
                time.sleep(wait_sec)
