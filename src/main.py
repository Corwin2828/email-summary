from __future__ import annotations

import atexit
import logging
import queue
import sys
import threading
import time

from src.app_state import save_last_active_at
from src.config import load_config
from src.imap_watcher import ImapWatcher
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
    def worker() -> None:
        while True:
            item = mail_queue.get()
            try:
                if item is None:
                    return
                account, uid, raw = item
                pipeline.handle_raw(account, uid, raw)
            except Exception:
                logger.exception("处理邮件失败")
            finally:
                mail_queue.task_done()

    t = threading.Thread(target=worker, name="mail-worker", daemon=True)
    t.start()
    return t


def main() -> None:
    try:
        config = load_config()
    except ValueError as e:
        logger.error("%s", e)
        logger.error("请复制 .env.example 为 .env 并填写配置")
        sys.exit(1)

    store = ProcessedStore(config.data_dir / "processed.db")
    atexit.register(lambda: save_last_active_at(config.data_dir))
    pipeline = EmailPipeline(config, store)
    mail_queue: queue.Queue[tuple[str, str, bytes] | None] = queue.Queue()
    _start_mail_worker(pipeline, mail_queue)

    mode = "IDLE" if config.imap_use_idle else f"轮询每 {config.poll_interval_sec}s"
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

    for account in config.accounts:

        def make_handler(acc_name: str):
            def handler(uid: str, raw: bytes) -> None:
                mail_queue.put((acc_name, uid, raw))

            return handler

        watcher = ImapWatcher(
            account,
            make_handler(account.name),
            data_dir=config.data_dir,
            process_existing_unread=config.process_existing_unread,
            catchup_since_last_run=config.catchup_since_last_run,
            use_idle=config.imap_use_idle,
            overquota_wait_sec=config.imap_overquota_wait_sec,
        )

        t = threading.Thread(
            target=watcher.run_forever,
            args=(config.poll_interval_sec,),
            name=f"imap-{account.name}",
            daemon=True,
        )
        t.start()
        logger.info("已启动监听线程: %s", account.name)

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
        mail_queue.join(timeout=30)
        save_last_active_at(config.data_dir)
        logger.info("已记录关闭时间，下次启动将补发此期间的邮件")
        store.close()


if __name__ == "__main__":
    main()
