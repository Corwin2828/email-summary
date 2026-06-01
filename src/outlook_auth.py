"""首次 Outlook OAuth 登录：python -m src.outlook_auth"""

from __future__ import annotations

import sys

from src.config import load_config
from src.outlook_oauth import ensure_outlook_token


def main() -> None:
    try:
        config = load_config()
    except ValueError as e:
        print(f"配置错误: {e}")
        sys.exit(1)

    outlook = next((a for a in config.accounts if a.use_oauth), None)
    if outlook is None:
        print("未启用 Outlook OAuth，请检查 .env 中 OUTLOOK_USE_OAUTH 与 AZURE_CLIENT_ID")
        sys.exit(1)

    ensure_outlook_token(
        outlook.address,
        outlook.azure_client_id,
        outlook.token_cache_path,  # type: ignore[arg-type]
    )
    print(f"\n登录成功，token 已保存。邮箱: {outlook.address}")


if __name__ == "__main__":
    main()
