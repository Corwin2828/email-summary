from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory

from src.config import ENV_PATH
from src.settings_store import (
    read_all_settings,
    save_all_settings,
    validate_settings,
)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

load_dotenv(ENV_PATH, override=True)


def create_app() -> Flask:
    app = Flask(__name__, static_folder=str(WEB_DIR), static_url_path="")
    app.config["MAX_CONTENT_LENGTH"] = int(
        os.getenv("WEB_MAX_CONTENT_LENGTH", "1048576")
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
    def get_settings() -> object:
        return jsonify(read_all_settings())

    @app.post("/api/settings")
    def post_settings() -> object:
        payload = request.get_json(silent=True) or {}
        errors = validate_settings(payload)
        if errors:
            return jsonify({"ok": False, "errors": errors}), 400
        try:
            save_all_settings(payload)
            return jsonify(
                {
                    "ok": True,
                    "message": "已保存。请重启 ./run.sh 使邮件监听生效。",
                }
            )
        except OSError as e:
            return jsonify({"ok": False, "errors": [str(e)]}), 500

    return app


def main() -> None:
    load_dotenv(ENV_PATH, override=True)
    host = os.getenv("WEB_HOST", "127.0.0.1")
    port = int(os.getenv("WEB_PORT", "8765"))
    app = create_app()
    print(f"配置页面: http://{host}:{port}/")
    print("仅本机访问，关闭请 Ctrl+C")
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
