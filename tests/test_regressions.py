from __future__ import annotations

import os
import json
import queue
import tempfile
import time
import unittest
from email.message import EmailMessage
from pathlib import Path

import dotenv

dotenv.load_dotenv = lambda *args, **kwargs: False

from src import config as cfg
from src import main as main_mod
from src import pipeline as pipeline_mod
from src import settings_store, web_app
from src.auth_store import set_user_password
from src.deepseek_client import DeepSeekClient
from src.email_parser import ParsedEmail, parse_raw_email
from src.filter_rules import classify_email
from src.imap_watcher import ImapWatcher
from src.prompts import BUSINESS_FILTER_GUARDRAILS, DEFAULT_BUSINESS_FILTER
from src.storage import ProcessedStore


def make_raw(
    subject: str = "Hello",
    sender: str = "Client <client@example.com>",
    to: str = "collector@example.com",
    body: str = "Hello body",
) -> bytes:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = "Sun, 28 Jun 2026 12:00:00 +0800"
    msg.set_content(body)
    return msg.as_bytes()


class RegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="email-summary-tests-")
        self.tmp = Path(self._tmp.name)
        for key in set(settings_store.ENV_KEYS) | {
            "FORWARD_SOURCE_MAP",
            "WEB_SESSION_SECRET",
        }:
            os.environ.pop(key, None)
        os.environ["DATA_DIR"] = str(self.tmp / "data")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_business_email_defaults_to_ai_filter(self) -> None:
        os.environ.update(
            {
                "DEEPSEEK_API_KEY": "fake-personal-key",
                "BUSINESS_EMAIL_ENABLED": "true",
                "BUSINESS_EMAIL_NAME": "aebbs-support",
                "BUSINESS_EMAIL_ADDRESS": "support@example.com",
                "BUSINESS_EMAIL_IMAP_HOST": "imap.example.com",
                "BUSINESS_EMAIL_PASSWORD": "fake-password",
                "BUSINESS_DEEPSEEK_API_KEY": "fake-business-key",
                "BUSINESS_FEISHU_WEBHOOK_URL": "https://example.invalid/hook",
            }
        )

        app_config = cfg.load_config()

        self.assertEqual(app_config.filter_mode, "ai")
        self.assertFalse(app_config.accounts[0].bypass_filter)
        self.assertIn("不确定一律回答 KEEP", DEFAULT_BUSINESS_FILTER)
        self.assertIn("只有在非常确定时才跳过", DEFAULT_BUSINESS_FILTER)

    def test_source_map_does_not_make_direct_mail_forwarded(self) -> None:
        parsed = parse_raw_email(
            "gmail",
            "1",
            make_raw(subject="Direct customer mail", body="Need a quote"),
            "collector@example.com",
            {"old@example.com": "Old Inbox"},
        )

        self.assertFalse(parsed.is_forwarded)
        self.assertEqual(parsed.forward_via, "")

    def test_forwarded_block_still_uses_source_map_label(self) -> None:
        body = """Please see below

---------- Forwarded message ----------
From: Buyer <buyer@example.com>
To: old@example.com
Subject: Need headlights

Can you quote?"""
        parsed = parse_raw_email(
            "gmail",
            "2",
            make_raw(
                subject="Fwd: Need headlights",
                sender="Me <collector@example.com>",
                body=body,
            ),
            "collector@example.com",
            {"old@example.com": "Old Inbox"},
        )

        self.assertTrue(parsed.is_forwarded)
        self.assertIn("buyer@example.com", parsed.original_sender.lower())
        self.assertTrue(parsed.forward_via.startswith("Old Inbox"))

    def test_business_filter_guardrails_apply_to_custom_prompt(self) -> None:
        data_dir = self.tmp / "guardrails"
        data_dir.mkdir(parents=True)
        (data_dir / "prompts.json").write_text(
            json.dumps(
                {
                    "business_filter_system": "OLD BUSINESS PROMPT",
                }
            ),
            encoding="utf-8",
        )
        account = cfg.AccountConfig(
            name="aebbs-support",
            host="imap.example.com",
            port=993,
            address="support@example.com",
            password="pw",
            purpose="business",
        )
        app_config = cfg.AppConfig(
            deepseek_api_key="fake",
            deepseek_base_url="https://example.invalid",
            deepseek_model="deepseek-chat",
            business_deepseek_api_key="fake-business",
            business_deepseek_base_url="https://example.invalid",
            business_deepseek_model="deepseek-chat",
            accounts=[account],
            feishu_webhook=None,
            wecom_webhook=None,
            business_feishu_webhook="https://example.invalid/hook",
            business_wecom_webhook=None,
            poll_interval_sec=900,
            data_dir=data_dir,
            max_body_chars=1000,
            filter_mode="ai",
            notify_format="ai",
            daily_digest_enabled=False,
            daily_digest_time="21:30",
            process_existing_unread=False,
            catchup_since_last_run=True,
            imap_use_idle=False,
            imap_overquota_wait_sec=10800,
            heartbeat_alert_enabled=True,
            heartbeat_stall_sec=7200,
            heartbeat_check_sec=300,
            forward_source_map={},
        )
        client = DeepSeekClient(app_config)
        captured: dict[str, str] = {}

        def fake_chat(system: str, user: str, purpose: str = "personal") -> str:
            captured["system"] = system
            captured["purpose"] = purpose
            return "KEEP"

        client._chat = fake_chat  # type: ignore[method-assign]
        email = ParsedEmail(
            "aebbs-support",
            "3",
            "Need quote",
            "buyer@example.com",
            "",
            "Can you quote headlights?",
        )

        self.assertTrue(client.should_keep_ai(email, "support@example.com"))
        self.assertEqual(captured["purpose"], "business")
        self.assertIn("OLD BUSINESS PROMPT", captured["system"])
        self.assertIn(BUSINESS_FILTER_GUARDRAILS, captured["system"])

    def test_personal_failures_retry_without_marking_processed(self) -> None:
        original_ai = pipeline_mod.DeepSeekClient
        original_alert = pipeline_mod.notify_system_issue

        class FailingAI:
            def __init__(self, config: cfg.AppConfig) -> None:
                self.config = config

            def should_keep_ai(self, parsed, aggregator_address):
                raise RuntimeError("fake filter failure")

        pipeline_mod.DeepSeekClient = FailingAI
        self.addCleanup(setattr, pipeline_mod, "DeepSeekClient", original_ai)
        pipeline_mod.notify_system_issue = lambda *args, **kwargs: []
        self.addCleanup(
            setattr,
            pipeline_mod,
            "notify_system_issue",
            original_alert,
        )

        account = cfg.AccountConfig(
            name="gmail",
            host="imap.example.com",
            port=993,
            address="collector@example.com",
            password="pw",
        )
        app_config = cfg.AppConfig(
            deepseek_api_key="fake",
            deepseek_base_url="https://example.invalid",
            deepseek_model="deepseek-chat",
            business_deepseek_api_key="",
            business_deepseek_base_url="https://example.invalid",
            business_deepseek_model="deepseek-chat",
            accounts=[account],
            feishu_webhook="https://example.invalid/hook",
            wecom_webhook=None,
            business_feishu_webhook=None,
            business_wecom_webhook=None,
            poll_interval_sec=900,
            data_dir=self.tmp / "pipeline",
            max_body_chars=1000,
            filter_mode="ai",
            notify_format="ai",
            daily_digest_enabled=False,
            daily_digest_time="21:30",
            process_existing_unread=False,
            catchup_since_last_run=True,
            imap_use_idle=False,
            imap_overquota_wait_sec=10800,
            heartbeat_alert_enabled=True,
            heartbeat_stall_sec=7200,
            heartbeat_check_sec=300,
            forward_source_map={},
        )
        store = ProcessedStore(self.tmp / "processed.db")
        self.addCleanup(store.close)
        pipe = pipeline_mod.EmailPipeline(app_config, store)
        raw = make_raw(subject="Need follow-up", body="Please review.")

        for _ in range(5):
            self.assertFalse(pipe.handle_raw("gmail", "10", raw))
            self.assertFalse(store.seen("gmail", "10"))
            self.assertEqual(store.pending_failed("gmail"), ["10"])

    def test_mail_worker_requeues_unhandled_pipeline_exception(self) -> None:
        class FlakyPipeline:
            def __init__(self) -> None:
                self.calls = 0
                self.failed: list[tuple[str, str]] = []

            def handle_raw(self, account: str, uid: str, raw: bytes) -> bool:
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError("unexpected worker failure")
                return True

            def mark_failed_for_retry(self, account: str, uid: str) -> None:
                self.failed.append((account, uid))

            def retry_delay_for(self, account: str) -> float:
                return 0.01

        pipeline = FlakyPipeline()
        mail_queue: queue.Queue[tuple[str, str, bytes] | None] = queue.Queue()
        worker = main_mod._start_mail_worker(pipeline, mail_queue)  # type: ignore[arg-type]
        mail_queue.put(("gmail", "99", make_raw()))

        deadline = time.time() + 2
        while time.time() < deadline and pipeline.calls < 2:
            time.sleep(0.01)

        mail_queue.put(None)
        mail_queue.join()
        worker.join(timeout=1)

        self.assertEqual(pipeline.calls, 2)
        self.assertEqual(pipeline.failed, [("gmail", "99")])
        self.assertFalse(worker.is_alive())

    def test_watcher_prioritizes_persisted_failed_retry_uids(self) -> None:
        raw = make_raw(subject="Retry me")
        account = cfg.AccountConfig(
            name="gmail",
            host="imap.example.com",
            port=993,
            address="collector@example.com",
            password="pw",
        )

        class FakeClient:
            def __init__(self) -> None:
                self.search_called = False

            def fetch(self, uids, parts):
                return {42: {b"RFC822": raw}}

            def search(self, criteria):
                self.search_called = True
                return []

        client = FakeClient()
        cleared: list[tuple[str, str]] = []
        watcher = ImapWatcher(
            account,
            lambda _uid, _raw: None,
            data_dir=self.tmp / "data",
            retry_uids_provider=lambda account_name: ["42"],
            retry_uid_clearer=lambda account_name, uid: cleared.append(
                (account_name, uid)
            ),
        )
        watcher._ensure_client = lambda: client  # type: ignore[method-assign]

        self.assertEqual(watcher.fetch_pending(), [("42", raw)])
        self.assertFalse(client.search_called)
        self.assertEqual(cleared, [])

    def test_watcher_clears_missing_failed_retry_uid_and_continues(self) -> None:
        account = cfg.AccountConfig(
            name="gmail",
            host="imap.example.com",
            port=993,
            address="collector@example.com",
            password="pw",
        )

        class FakeClient:
            def __init__(self) -> None:
                self.search_called = False

            def fetch(self, uids, parts):
                return {}

            def search(self, criteria):
                self.search_called = True
                return []

        client = FakeClient()
        cleared: list[tuple[str, str]] = []
        watcher = ImapWatcher(
            account,
            lambda _uid, _raw: None,
            data_dir=self.tmp / "data",
            retry_uids_provider=lambda account_name: ["404"],
            retry_uid_clearer=lambda account_name, uid: cleared.append(
                (account_name, uid)
            ),
        )
        watcher._ensure_client = lambda: client  # type: ignore[method-assign]

        self.assertEqual(watcher.fetch_pending(), [])
        self.assertEqual(cleared, [("gmail", "404")])
        self.assertTrue(client.search_called)

    def test_watcher_existing_unread_skips_submitted_uids(self) -> None:
        account = cfg.AccountConfig(
            name="aebbs",
            host="imap.example.com",
            port=993,
            address="support@example.com",
            password="pw",
            process_existing_unread=True,
            purpose="business",
        )

        class FakeClient:
            def __init__(self) -> None:
                self.fetch_calls: list[list[int]] = []

            def fetch(self, uids, parts):
                requested = list(uids)
                self.fetch_calls.append(requested)
                return {
                    uid: {b"RFC822": make_raw(subject=f"Unread {uid}")}
                    for uid in requested
                }

            def search(self, criteria):
                return list(range(1, 22))

        client = FakeClient()
        emitted: list[str] = []
        watcher = ImapWatcher(
            account,
            lambda uid, _raw: emitted.append(uid),
            data_dir=self.tmp / "data",
            process_existing_unread=True,
        )
        watcher._ensure_client = lambda: client  # type: ignore[method-assign]

        first = watcher.fetch_pending()
        for uid, raw in first:
            watcher._emit(uid, raw)
        second = watcher.fetch_pending()

        self.assertEqual([uid for uid, _raw in first], [str(i) for i in range(1, 21)])
        self.assertEqual([uid for uid, _raw in second], ["21"])
        self.assertEqual(client.fetch_calls, [list(range(1, 21)), [21]])
        self.assertEqual(emitted, [str(i) for i in range(1, 21)])

    def test_successful_processing_clears_persisted_failed_retry(self) -> None:
        original_ai = pipeline_mod.DeepSeekClient
        original_send_text = pipeline_mod.send_text

        class PassingAI:
            def __init__(self, config: cfg.AppConfig) -> None:
                self.config = config

            def should_keep_ai(self, parsed, aggregator_address):
                return True

            def compose_notification(self, parsed, aggregator_address):
                return "ok"

        pipeline_mod.DeepSeekClient = PassingAI
        pipeline_mod.send_text = lambda *args, **kwargs: None
        self.addCleanup(setattr, pipeline_mod, "DeepSeekClient", original_ai)
        self.addCleanup(setattr, pipeline_mod, "send_text", original_send_text)

        account = cfg.AccountConfig(
            name="gmail",
            host="imap.example.com",
            port=993,
            address="collector@example.com",
            password="pw",
        )
        app_config = cfg.AppConfig(
            deepseek_api_key="fake",
            deepseek_base_url="https://example.invalid",
            deepseek_model="deepseek-chat",
            business_deepseek_api_key="",
            business_deepseek_base_url="https://example.invalid",
            business_deepseek_model="deepseek-chat",
            accounts=[account],
            feishu_webhook="https://example.invalid/hook",
            wecom_webhook=None,
            business_feishu_webhook=None,
            business_wecom_webhook=None,
            poll_interval_sec=900,
            data_dir=self.tmp / "pipeline-success",
            max_body_chars=1000,
            filter_mode="ai",
            notify_format="ai",
            daily_digest_enabled=False,
            daily_digest_time="21:30",
            process_existing_unread=False,
            catchup_since_last_run=True,
            imap_use_idle=False,
            imap_overquota_wait_sec=10800,
            heartbeat_alert_enabled=True,
            heartbeat_stall_sec=7200,
            heartbeat_check_sec=300,
            forward_source_map={},
        )
        store = ProcessedStore(self.tmp / "processed-success.db")
        self.addCleanup(store.close)
        store.mark_failed("gmail", "11")
        pipe = pipeline_mod.EmailPipeline(app_config, store)

        self.assertTrue(pipe.handle_raw("gmail", "11", make_raw()))
        self.assertTrue(store.seen("gmail", "11"))
        self.assertEqual(store.pending_failed("gmail"), [])

    def test_poll_once_uses_persisted_failed_retry_store(self) -> None:
        raw = make_raw(subject="Manual retry")
        account = cfg.AccountConfig(
            name="gmail",
            host="imap.example.com",
            port=993,
            address="collector@example.com",
            password="pw",
        )
        app_config = cfg.AppConfig(
            deepseek_api_key="fake",
            deepseek_base_url="https://example.invalid",
            deepseek_model="deepseek-chat",
            business_deepseek_api_key="",
            business_deepseek_base_url="https://example.invalid",
            business_deepseek_model="deepseek-chat",
            accounts=[account],
            feishu_webhook="https://example.invalid/hook",
            wecom_webhook=None,
            business_feishu_webhook=None,
            business_wecom_webhook=None,
            poll_interval_sec=900,
            data_dir=self.tmp / "poll-once",
            max_body_chars=1000,
            filter_mode="ai",
            notify_format="ai",
            daily_digest_enabled=False,
            daily_digest_time="21:30",
            process_existing_unread=False,
            catchup_since_last_run=True,
            imap_use_idle=False,
            imap_overquota_wait_sec=10800,
            heartbeat_alert_enabled=True,
            heartbeat_stall_sec=7200,
            heartbeat_check_sec=300,
            forward_source_map={},
        )
        store = ProcessedStore(self.tmp / "processed-poll-once.db")
        self.addCleanup(store.close)
        store.mark_failed("gmail", "77")

        class FakePipeline:
            def __init__(self) -> None:
                self.calls: list[tuple[str, str, bytes]] = []
                self.marked: list[tuple[str, str]] = []
                self.mark_attempts = 0

            def mark_failed_for_retry(self, account_name: str, uid: str) -> None:
                self.mark_attempts += 1
                if self.mark_attempts == 1:
                    raise RuntimeError("temporary db failure")
                self.marked.append((account_name, uid))
                store.mark_failed(account_name, uid)

            def handle_raw(self, account_name: str, uid: str, raw_bytes: bytes) -> bool:
                self.calls.append((account_name, uid, raw_bytes))
                store.mark(account_name, uid)
                store.clear_failed(account_name, uid)
                return True

        class FakeWatcher:
            def __init__(
                self,
                _account,
                _on_message,
                *,
                retry_uids_provider=None,
                retry_uid_clearer=None,
                **_kwargs,
            ) -> None:
                self.retry_uids_provider = retry_uids_provider
                self.retry_uid_clearer = retry_uid_clearer
                self.closed = False

            def fetch_pending(self):
                if self.retry_uids_provider is None:
                    return []
                if "77" in self.retry_uids_provider("gmail"):
                    return [("77", raw)]
                return []

            def close(self) -> None:
                self.closed = True

        original_watcher = main_mod.ImapWatcher
        main_mod.ImapWatcher = FakeWatcher  # type: ignore[assignment]
        self.addCleanup(setattr, main_mod, "ImapWatcher", original_watcher)

        fake_pipeline = FakePipeline()
        main_mod._poll_once(app_config, fake_pipeline, store)  # type: ignore[arg-type]

        self.assertEqual(fake_pipeline.calls, [("gmail", "77", raw)])
        self.assertEqual(fake_pipeline.mark_attempts, 1)
        self.assertEqual(fake_pipeline.marked, [])
        self.assertTrue(store.seen("gmail", "77"))
        self.assertEqual(store.pending_failed("gmail"), [])

    def test_web_numeric_validation_and_login_attempt_reset(self) -> None:
        settings_store.ENV_PATH = self.tmp / ".env"
        payload = {
            "env": {
                "DEEPSEEK_API_KEY": "fake",
                "GMAIL_ENABLED": "true",
                "GMAIL_ADDRESS": "user@example.com",
                "GMAIL_APP_PASSWORD": "pw",
                "FEISHU_WEBHOOK_URL": "https://example.invalid/hook",
                "POLL_INTERVAL_SEC": "900",
                "WEB_PORT": "bad-port",
                "WEB_MAX_CONTENT_LENGTH": "bad-bytes",
                "WEB_LOGIN_MAX_ATTEMPTS": "bad-attempts",
                "WEB_LOGIN_WINDOW_SEC": "bad-window",
                "FILTER_MODE": "maybe",
                "NOTIFY_FORMAT": "plain",
            }
        }

        errors = settings_store.validate_settings(payload)

        self.assertIn("网页端口必须是数字", errors)
        self.assertIn("网页请求体大小限制必须是数字", errors)
        self.assertIn("登录失败次数限制必须是数字", errors)
        self.assertIn("登录失败统计窗口秒数必须是数字", errors)
        self.assertIn("过滤模式必须选择: ai、rules", errors)
        self.assertIn("通知格式必须选择: ai、template", errors)

        os.environ["WEB_MAX_CONTENT_LENGTH"] = "bad-bytes"
        os.environ["WEB_LOGIN_MAX_ATTEMPTS"] = "2"
        os.environ["WEB_LOGIN_WINDOW_SEC"] = "600"
        web_app.LOGIN_ATTEMPTS.clear()
        set_user_password("owner", "CorrectHorse123", "owner", self.tmp / "data")
        app = web_app.create_app()
        app.testing = True
        client = app.test_client()

        self.assertEqual(
            client.post(
                "/api/login",
                json={"username": "owner", "password": "bad"},
            ).status_code,
            401,
        )
        self.assertEqual(
            client.post(
                "/api/login",
                json={"username": "owner", "password": "CorrectHorse123"},
            ).status_code,
            200,
        )
        self.assertEqual(
            client.post(
                "/api/login",
                json={"username": "owner", "password": "bad"},
            ).status_code,
            401,
        )
        self.assertEqual(
            client.post(
                "/api/login",
                json={"username": "owner", "password": "CorrectHorse123"},
            ).status_code,
            200,
        )

    def test_owner_settings_can_reveal_secret_values(self) -> None:
        settings_store.ENV_PATH = self.tmp / ".env"
        settings_store.ENV_PATH.write_text(
            "\n".join(
                [
                    "DEEPSEEK_API_KEY=visible-personal-key",
                    "FEISHU_WEBHOOK_URL=https://example.invalid/personal-hook",
                    "BUSINESS_DEEPSEEK_API_KEY=visible-business-key",
                    "BUSINESS_FEISHU_WEBHOOK_URL=https://example.invalid/business-hook",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        masked = settings_store.read_all_settings()
        revealed = settings_store.read_all_settings(reveal_secrets=True)

        self.assertEqual(masked["env"]["DEEPSEEK_API_KEY"], "")
        self.assertEqual(masked["env"]["FEISHU_WEBHOOK_URL"], "")
        self.assertEqual(
            revealed["env"]["DEEPSEEK_API_KEY"],
            "visible-personal-key",
        )
        self.assertEqual(
            revealed["env"]["BUSINESS_FEISHU_WEBHOOK_URL"],
            "https://example.invalid/business-hook",
        )

    def test_saving_settings_runs_webhook_and_api_diagnostics(self) -> None:
        settings_store.ENV_PATH = self.tmp / ".env"
        captured: dict[str, object] = {}
        original_load_config = web_app.load_config
        original_diagnostics = web_app.run_settings_diagnostics

        def fake_load_config() -> object:
            return object()

        def fake_diagnostics(config, username: str, changed_items: list[str]) -> dict:
            captured["username"] = username
            captured["changed_items"] = changed_items
            return {
                "webhooks": [
                    {
                        "purpose": "personal",
                        "channel": "飞书",
                        "ok": True,
                        "detail": "已发送",
                    }
                ],
                "apis": [
                    {
                        "name": "个人邮箱 DeepSeek",
                        "ok": True,
                        "detail": "API 可用",
                    }
                ],
            }

        web_app.load_config = fake_load_config  # type: ignore[assignment]
        web_app.run_settings_diagnostics = fake_diagnostics  # type: ignore[assignment]
        self.addCleanup(setattr, web_app, "load_config", original_load_config)
        self.addCleanup(
            setattr,
            web_app,
            "run_settings_diagnostics",
            original_diagnostics,
        )

        set_user_password("owner", "CorrectHorse123", "owner", self.tmp / "data")
        app = web_app.create_app()
        app.testing = True
        client = app.test_client()
        login = client.post(
            "/api/login",
            json={"username": "owner", "password": "CorrectHorse123"},
        )
        csrf = login.get_json()["csrf_token"]
        payload = {
            "env": {
                "DEEPSEEK_API_KEY": "fake",
                "GMAIL_ENABLED": "true",
                "GMAIL_ADDRESS": "user@example.com",
                "GMAIL_APP_PASSWORD": "pw",
                "FEISHU_WEBHOOK_URL": "https://example.invalid/hook",
                "POLL_INTERVAL_SEC": "900",
            },
            "prompts": {},
        }

        resp = client.post(
            "/api/settings",
            json=payload,
            headers={"X-CSRF-Token": csrf},
        )

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["diagnostics"]["webhooks"][0]["ok"], True)
        self.assertEqual(captured["username"], "owner")
        self.assertIn("GMAIL_ADDRESS", captured["changed_items"])

    def test_rules_mode_keeps_work_mail_about_verification_flow(self) -> None:
        email = ParsedEmail(
            "gmail",
            "4",
            "Feedback on SMS verification flow",
            "pm@example.com",
            "",
            "客户反馈短信验证流程出错，需要产品和工程一起跟进。不是一次性验证码邮件。",
        )

        result = classify_email(email, verification_mode="strict")

        self.assertTrue(result.should_summarize, result)

    def test_rules_mode_skips_alphanumeric_verification_code(self) -> None:
        email = ParsedEmail(
            "gmail",
            "5",
            "Security notice",
            "security@example.com",
            "",
            "Your verification code is ABCD7. It expires in 10 minutes.",
        )

        result = classify_email(email, verification_mode="strict")

        self.assertFalse(result.should_summarize, result)


if __name__ == "__main__":
    unittest.main()
