from __future__ import annotations

import logging
import ssl
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path

from imapclient import IMAPClient

from src.app_state import load_last_active_at, save_last_active_at
from src.config import AccountConfig

logger = logging.getLogger(__name__)

MAX_FETCH_PER_POLL = 20


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
    ) -> None:
        self._account = account
        self._on_message = on_message
        self._data_dir = data_dir
        self._idle_timeout = idle_timeout_sec
        self._process_existing_unread = process_existing_unread
        self._catchup_since_last_run = catchup_since_last_run
        self._use_idle = use_idle
        self._runtime_baseline: set[str] | None = None
        self._catchup_done = False
        self._submitted_uids: set[str] = set()
        self._client: IMAPClient | None = None

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

        last = load_last_active_at(self._data_dir)
        if last is None:
            save_last_active_at(self._data_dir)
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

        return self._fetch_uids(client, uids)

    def run_poll_forever(self, poll_interval_sec: int) -> None:
        while True:
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
                logger.warning(
                    "%s 轮询失败，%ss 后重试: %s",
                    self._account.name,
                    poll_interval_sec,
                    e,
                )
                self._disconnect()
            time.sleep(poll_interval_sec)

    def run_forever(self, poll_fallback_sec: int) -> None:
        if not self._use_idle:
            self.run_poll_forever(poll_fallback_sec)
            return

        while True:
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
                        logger.warning(
                            "%s IDLE 中断，%ss 后重连: %s",
                            self._account.name,
                            poll_fallback_sec,
                            e,
                        )
                        self._disconnect()
                        time.sleep(min(poll_fallback_sec, 30))
                        break

            except Exception as e:
                logger.error(
                    "%s 连接失败，%ss 后重试: %s",
                    self._account.name,
                    poll_fallback_sec,
                    e,
                )
                self._disconnect()
                time.sleep(poll_fallback_sec)
