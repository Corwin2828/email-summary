from __future__ import annotations

import os
import secrets
import time
from functools import wraps
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory, session

from src.auth_store import WebUser, load_session_secret, list_users, verify_user
from src.config import ENV_PATH, load_config, resolve_data_dir
from src.diagnostics import run_settings_diagnostics
from src.rag_store import list_rag_files, read_rag_file, save_rag_file
from src.settings_store import (
    ENV_KEYS,
    read_all_settings,
    read_prompt_settings,
    save_all_settings,
    save_prompt_settings,
    validate_settings,
)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

load_dotenv(ENV_PATH, override=True)

LOGIN_ATTEMPTS: dict[str, list[float]] = {}


def _int_env(
    name: str,
    default: int,
    minimum: int,
    maximum: int | None = None,
) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def _login_limited(remote: str) -> bool:
    now = time.time()
    window_sec = _int_env("WEB_LOGIN_WINDOW_SEC", 600, 60)
    max_attempts = _int_env("WEB_LOGIN_MAX_ATTEMPTS", 8, 1)
    attempts = [ts for ts in LOGIN_ATTEMPTS.get(remote, []) if now - ts < window_sec]
    LOGIN_ATTEMPTS[remote] = attempts
    return len(attempts) >= max_attempts


def _record_login_failure(remote: str) -> None:
    LOGIN_ATTEMPTS.setdefault(remote, []).append(time.time())


def _current_user() -> WebUser | None:
    username = session.get("username")
    role = session.get("role")
    if isinstance(username, str) and role in {"owner", "team"}:
        return WebUser(username=username, role=role)
    return None


def _csrf_token() -> str:
    token = session.get("csrf_token")
    if not isinstance(token, str):
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def _safe_user(user: WebUser | None) -> dict | None:
    if user is None:
        return None
    return {
        "username": user.username,
        "role": user.role,
        "can_manage_settings": user.role == "owner",
        "can_manage_rag": user.role in {"owner", "team"},
    }


def _changed_settings(before: dict, after: dict) -> list[str]:
    changed: list[str] = []
    before_env = before.get("env") or {}
    after_env = after.get("env") or {}
    for key in ENV_KEYS:
        if before_env.get(key, "") != after_env.get(key, ""):
            changed.append(key)

    before_prompts = before.get("prompts") or {}
    after_prompts = after.get("prompts") or {}
    for key in (
        "summary_system",
        "filter_system",
        "business_summary_system",
        "business_filter_system",
    ):
        if before_prompts.get(key, "") != after_prompts.get(key, ""):
            changed.append(f"prompt:{key}")
    return changed


def require_auth(owner_only: bool = False):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = _current_user()
            if user is None:
                return jsonify({"ok": False, "error": "unauthorized"}), 401
            if owner_only and user.role != "owner":
                return jsonify({"ok": False, "error": "forbidden"}), 403
            if request.method not in {"GET", "HEAD", "OPTIONS"}:
                token = request.headers.get("X-CSRF-Token", "")
                if not token or not secrets.compare_digest(token, _csrf_token()):
                    return jsonify({"ok": False, "error": "bad csrf"}), 403
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def create_app() -> Flask:
    app = Flask(__name__, static_folder=str(WEB_DIR), static_url_path="")
    data_dir = resolve_data_dir()
    app.secret_key = os.getenv("WEB_SESSION_SECRET") or load_session_secret(data_dir)
    app.config["MAX_CONTENT_LENGTH"] = _int_env(
        "WEB_MAX_CONTENT_LENGTH",
        1048576,
        1024,
    )
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("WEB_COOKIE_SECURE", "").lower()
        in ("1", "true", "yes", "on"),
    )

    @app.after_request
    def add_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "style-src 'self' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "script-src 'self'; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'",
        )
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/")
    def index() -> object:
        return send_from_directory(WEB_DIR, "index.html")

    @app.get("/app.js")
    def app_js() -> object:
        return send_from_directory(WEB_DIR, "app.js")

    @app.get("/app.css")
    def app_css() -> object:
        return send_from_directory(WEB_DIR, "app.css")

    @app.get("/api/settings")
    @require_auth(owner_only=True)
    def get_settings() -> object:
        return jsonify(read_all_settings(reveal_secrets=True))

    @app.post("/api/settings")
    @require_auth(owner_only=True)
    def post_settings() -> object:
        user = _current_user()
        payload = request.get_json(silent=True) or {}
        errors = validate_settings(payload)
        if errors:
            return jsonify({"ok": False, "errors": errors}), 400
        before = read_all_settings(reveal_secrets=True)
        try:
            save_all_settings(payload)
            after = read_all_settings(reveal_secrets=True)
            changed = _changed_settings(before, after)
            try:
                config = load_config()
                diagnostics = run_settings_diagnostics(
                    config,
                    user.username if user else "owner",
                    changed,
                )
                return jsonify(
                    {
                        "ok": True,
                        "message": "已保存，并已完成 Webhook/API 连通性检查。",
                        "diagnostics": diagnostics,
                    }
                )
            except Exception as e:
                return jsonify(
                    {
                        "ok": True,
                        "message": "已保存，但保存后诊断未完成，请查看下方结果。",
                        "diagnostics": {
                            "webhooks": [],
                            "apis": [
                                {
                                    "name": "配置加载",
                                    "ok": False,
                                    "detail": str(e)[:240],
                                }
                            ],
                        },
                    }
                )
        except OSError as e:
            return jsonify({"ok": False, "errors": [str(e)]}), 500

    @app.get("/api/session")
    def get_session() -> object:
        user = _current_user()
        users_ready = bool(list_users(data_dir))
        return jsonify(
            {
                "ok": True,
                "user": _safe_user(user),
                "csrf_token": _csrf_token() if user else None,
                "users_ready": users_ready,
            }
        )

    @app.post("/api/login")
    def login() -> object:
        remote = request.remote_addr or "local"
        if _login_limited(remote):
            return jsonify({"ok": False, "error": "too many attempts"}), 429
        payload = request.get_json(silent=True) or {}
        username = str(payload.get("username") or "").strip()
        password = str(payload.get("password") or "")
        user = verify_user(username, password, data_dir)
        if user is None:
            _record_login_failure(remote)
            return jsonify({"ok": False, "error": "invalid login"}), 401
        LOGIN_ATTEMPTS.pop(remote, None)
        session.clear()
        session["username"] = user.username
        session["role"] = user.role
        token = _csrf_token()
        return jsonify({"ok": True, "user": _safe_user(user), "csrf_token": token})

    @app.post("/api/logout")
    @require_auth()
    def logout() -> object:
        session.clear()
        return jsonify({"ok": True})

    @app.get("/api/prompts")
    @require_auth()
    def get_prompts() -> object:
        user = _current_user()
        return jsonify(
            {
                "ok": True,
                "prompts": read_prompt_settings(owner=user.role == "owner"),  # type: ignore[union-attr]
            }
        )

    @app.post("/api/prompts")
    @require_auth()
    def post_prompts() -> object:
        user = _current_user()
        payload = request.get_json(silent=True) or {}
        save_prompt_settings(payload, owner=user.role == "owner")  # type: ignore[union-attr]
        return jsonify({"ok": True, "message": "Prompt 已保存"})

    @app.get("/api/rag/files")
    @require_auth()
    def get_rag_files() -> object:
        return jsonify({"ok": True, "files": list_rag_files()})

    @app.get("/api/rag/file")
    @require_auth()
    def get_rag_file() -> object:
        path = request.args.get("path", "")
        try:
            return jsonify({"ok": True, "file": read_rag_file(path)})
        except (FileNotFoundError, ValueError) as e:
            return jsonify({"ok": False, "error": str(e)}), 400

    @app.post("/api/rag/file")
    @require_auth()
    def post_rag_file() -> object:
        payload = request.get_json(silent=True) or {}
        try:
            saved = save_rag_file(
                str(payload.get("path") or ""),
                str(payload.get("content") or ""),
            )
            return jsonify({"ok": True, "file": saved, "message": "知识库文件已保存"})
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400

    return app


def main() -> None:
    load_dotenv(ENV_PATH, override=True)
    host = os.getenv("WEB_HOST", "127.0.0.1")
    port = _int_env("WEB_PORT", 8765, 1, 65535)
    app = create_app()
    print(f"配置页面: http://{host}:{port}/")
    print("仅本机访问，关闭请 Ctrl+C")
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
