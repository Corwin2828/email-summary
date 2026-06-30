from __future__ import annotations

import os
import json
import tempfile
import unittest
from email.message import EmailMessage
from pathlib import Path

import dotenv

dotenv.load_dotenv = lambda *args, **kwargs: False

from src import config as cfg
from src import pipeline as pipeline_mod
from src import settings_store, web_app
from src.auth_store import set_user_password
from src.deepseek_client import DeepSeekClient
from src.email_parser import ParsedEmail, parse_raw_email
from src.filter_rules import classify_email
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

        class FailingAI:
            def __init__(self, config: cfg.AppConfig) -> None:
                self.config = config

            def should_keep_ai(self, parsed, aggregator_address):
                raise RuntimeError("fake filter failure")

        pipeline_mod.DeepSeekClient = FailingAI
        self.addCleanup(setattr, pipeline_mod, "DeepSeekClient", original_ai)

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
            }
        }

        errors = settings_store.validate_settings(payload)

        self.assertIn("网页端口必须是数字", errors)
        self.assertIn("网页请求体大小限制必须是数字", errors)
        self.assertIn("登录失败次数限制必须是数字", errors)
        self.assertIn("登录失败统计窗口秒数必须是数字", errors)

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
