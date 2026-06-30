from __future__ import annotations

import argparse
import atexit
import logging
import queue
import sys
import threading
import time
import traceback
from datetime import datetime, timezone

from src.app_state import save_last_active_at
from src.config import AppConfig, load_config
from src.diagnostics import notify_system_issue, notify_system_started
from src.imap_watcher import ImapWatcher
from src.notify import send_text
from src.pipeline import EmailPipeline
from src.storage import ProcessedStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def _start_mail_worker(
    pipeline: EmailPipeline,
    mail_queue: queue.Queue[tuple[str, str, bytes] | None],
) -> threading.Thread:
    def retry_later(item: tuple[str, str, bytes], delay_sec: int) -> None:
        def requeue() -> None:
            mail_queue.put(item)

        timer = threading.Timer(delay_sec, requeue)
        timer.daemon = True
        timer.start()

    def worker() -> None:
        while True:
            item = mail_queue.get()
            try:
                if item is None:
                    return
                account, uid, raw = item
                done = pipeline.handle_raw(account, uid, raw)
                if not done:
                    delay_sec = pipeline.retry_delay_for(account)
                    logger.warning(
                        "%s/%s 本次未完成，将在 %ss 后重试",
                        account,
                        uid,
                        delay_sec,
                    )
                    retry_later(item, delay_sec)
            except Exception:
                logger.exception("处理邮件失败")
            finally:
                mail_queue.task_done()

    t = threading.Thread(target=worker, name="mail-worker", daemon=True)
    t.start()
    return t


def _alert_purpose(config: AppConfig) -> str:
    if config.feishu_webhook or config.wecom_webhook:
        return "personal"
    return "business"


def _make_imap_error_handler(
    config: AppConfig,
    account_label: str,
    purpose: str,
):
    """连续失败时给飞书/企微发告警。"""

    def handler(account_name: str, exc: Exception, count: int) -> None:
        # 只在 3、6、9... 次发送，避免刷屏
        text = (
            f"【邮件总结助手告警】\n"
            f"账户: {account_label or account_name}\n"
            f"IMAP 轮询/连接连续失败 {count} 次，请检查网络或 Gmail 限流。\n"
            f"最近一次错误: {exc}"
        )
        try:
            send_text(config, text, purpose)
        except Exception:
            logger.exception("发送 IMAP 错误告警失败")

    return handler


def _start_stall_monitor(
    config: AppConfig,
    mail_queue: queue.Queue[tuple[str, str, bytes] | None],
    get_last_activity_at,
) -> threading.Thread | None:
    """队列持续堆积且长时间无处理结果时发告警。"""
    if not config.heartbeat_alert_enabled:
        return None

    def monitor() -> None:
        alerting = False
        while True:
            time.sleep(config.heartbeat_check_sec)
            pending = mail_queue.qsize()
            if pending <= 0:
                alerting = False
                continue

            last_active = get_last_activity_at()
            idle_sec = int(
                (datetime.now(timezone.utc) - last_active).total_seconds()
            )
            if idle_sec < config.heartbeat_stall_sec:
                continue
            if alerting:
                continue

            text = (
                "【邮件总结助手告警】\n"
                "检测到处理疑似卡住：\n"
                f"- 待处理队列: {pending} 封\n"
                f"- 最近一次处理结果距今: {max(1, idle_sec // 60)} 分钟\n"
                f"- 阈值: {max(1, config.heartbeat_stall_sec // 60)} 分钟\n"
                "建议检查 DeepSeek/网络连通性；如已配置 daily restart，系统会在下一次窗口自动重启。"
            )
            try:
                send_text(config, text, _alert_purpose(config))
                logger.warning(
                    "已发送卡住告警：queue=%s idle=%ss", pending, idle_sec
                )
                alerting = True
            except Exception:
                logger.exception("发送卡住告警失败")

    t = threading.Thread(
        target=monitor,
        name="stall-monitor",
        daemon=True,
    )
    t.start()
    return t


def _poll_once(
    config: AppConfig,
    pipeline: EmailPipeline,
    account_filter: str | None = None,
) -> None:
    """手动执行一轮轮询并退出（用于后台人工触发）。"""
    total = 0

    for account in config.accounts:
        if account_filter and account.name != account_filter:
            continue
        watcher = ImapWatcher(
            account,
            lambda _uid, _raw: None,
            data_dir=config.data_dir,
            process_existing_unread=(
                account.process_existing_unread
                if account.process_existing_unread is not None
                else config.process_existing_unread
            ),
            catchup_since_last_run=config.catchup_since_last_run,
            use_idle=False,
            overquota_wait_sec=account.overquota_wait_sec
            or config.imap_overquota_wait_sec,
            quiet_hours_enabled=account.quiet_hours_enabled,
        )
        try:
            batch = watcher.fetch_pending()
            if batch:
                logger.info(
                    "[手动轮询] %s 发现 %d 封待处理邮件",
                    account.name,
                    len(batch),
                )
            for uid, raw in batch:
                pipeline.handle_raw(account.name, uid, raw)
                total += 1
        except Exception:
            logger.exception("[手动轮询] %s 失败", account.name)
        finally:
            watcher.close()

    logger.info("[手动轮询] 本轮结束，共处理 %d 封邮件", total)


def main() -> None:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument(
        "--poll-once",
        action="store_true",
        help="执行一次轮询后退出（不常驻）",
    )
    parser.add_argument(
        "--account",
        help="只处理指定账户名，例如 gmail / outlook / aebbs-support",
    )
    args = parser.parse_args()

    try:
        config = load_config()
    except ValueError as e:
        logger.error("%s", e)
        logger.error("请复制 .env.example 为 .env 并填写配置")
        sys.exit(1)

    store = ProcessedStore(config.data_dir / "processed.db")
    last_activity_lock = threading.Lock()
    last_activity_at = datetime.now(timezone.utc)

    def get_last_activity_at() -> datetime:
        with last_activity_lock:
            return last_activity_at

    def mark_activity(account_name: str) -> None:
        nonlocal last_activity_at
        now = datetime.now(timezone.utc)
        with last_activity_lock:
            last_activity_at = now
        save_last_active_at(config.data_dir, now, account_name)

    def save_shutdown_state() -> None:
        now = datetime.now(timezone.utc)
        for acc in config.accounts:
            save_last_active_at(config.data_dir, now, acc.name)

    atexit.register(save_shutdown_state)
    pipeline = EmailPipeline(config, store, on_activity=mark_activity)

    mode = "IDLE" if config.imap_use_idle else "定时轮询"
    logger.info("IMAP 模式: %s", mode)
    filter_label = (
        "DeepSeek 判断是否总结"
        if config.filter_mode == "ai"
        else "本地规则过滤"
    )
    logger.info("邮件过滤: %s (FILTER_MODE=%s)", filter_label, config.filter_mode)
    notify_label = (
        "DeepSeek 生成推送全文"
        if config.notify_format == "ai"
        else "本地模板拼装"
    )
    logger.info("通知格式: %s (NOTIFY_FORMAT=%s)", notify_label, config.notify_format)
    if config.catchup_since_last_run and not config.process_existing_unread:
        logger.info("已开启：启动时补发「上次关闭以来」的邮件总结")
    elif config.process_existing_unread:
        logger.info("已开启：处理收件箱全部未读（慎用）")

    for account in config.accounts:
        if account.use_oauth:
            from src.outlook_oauth import ensure_outlook_token

            logger.info("正在验证 Outlook OAuth 登录…")
            ensure_outlook_token(
                account.address,
                account.azure_client_id,
                account.token_cache_path,  # type: ignore[arg-type]
            )

    if args.poll_once:
        _poll_once(config, pipeline, args.account)
        store.close()
        return

    try:
        notify_system_started(config)
    except Exception:
        logger.exception("发送系统启动通知失败")

    mail_queue: queue.Queue[tuple[str, str, bytes] | None] = queue.Queue()
    _start_mail_worker(pipeline, mail_queue)
    _start_stall_monitor(config, mail_queue, get_last_activity_at)

    for account in config.accounts:

        def make_handler(acc_name: str):
            def handler(uid: str, raw: bytes) -> None:
                mail_queue.put((acc_name, uid, raw))

            return handler

        watcher = ImapWatcher(
            account,
            make_handler(account.name),
            data_dir=config.data_dir,
            process_existing_unread=(
                account.process_existing_unread
                if account.process_existing_unread is not None
                else config.process_existing_unread
            ),
            catchup_since_last_run=config.catchup_since_last_run,
            use_idle=config.imap_use_idle,
            overquota_wait_sec=account.overquota_wait_sec
            or config.imap_overquota_wait_sec,
            quiet_hours_enabled=account.quiet_hours_enabled,
        )
        watcher.set_error_callback(
            _make_imap_error_handler(
                config,
                account.address or account.name,
                account.purpose,
            )
        )

        poll_interval = account.poll_interval_sec or config.poll_interval_sec
        t = threading.Thread(
            target=watcher.run_forever,
            args=(poll_interval,),
            name=f"imap-{account.name}",
            daemon=True,
        )
        t.start()
        logger.info(
            "已启动监听线程: %s (%s, 每 %ss)",
            account.name,
            account.purpose,
            poll_interval,
        )

    logger.info(
        "邮件总结助手已运行。账户: %s | 按 Ctrl+C 退出",
        ", ".join(a.name for a in config.accounts),
    )

    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        logger.info("正在退出…")
        mail_queue.put(None)
        mail_queue.join()
        save_shutdown_state()
        logger.info("已记录关闭时间，下次启动将补发此期间的邮件")
        store.close()


def _notify_fatal_error(exc: Exception) -> None:
    try:
        config = load_config()
        notify_system_issue(
            config,
            "程序异常退出",
            "\n".join(
                [
                    f"错误: {exc}",
                    "主程序已异常退出，systemd 可能会尝试自动重启。",
                    traceback.format_exc()[-1200:],
                ]
            ),
        )
    except Exception:
        logger.exception("发送致命异常告警失败")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        logger.exception("程序异常退出")
        _notify_fatal_error(e)
        raise
