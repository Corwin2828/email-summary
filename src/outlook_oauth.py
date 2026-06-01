from __future__ import annotations

import logging
from pathlib import Path

import msal

logger = logging.getLogger(__name__)

IMAP_SCOPES = [
    "https://outlook.office.com/IMAP.AccessAsUser.All",
    "offline_access",
]
AUTHORITY = "https://login.microsoftonline.com/consumers"


def _cache_path(token_cache_path: Path | None) -> Path:
    if token_cache_path is None:
        raise ValueError("未配置 OAuth token 缓存路径")
    return token_cache_path


def _load_cache(path: Path) -> msal.SerializableTokenCache:
    cache = msal.SerializableTokenCache()
    if path.exists():
        cache.deserialize(path.read_text(encoding="utf-8"))
    return cache


def _save_cache(cache: msal.SerializableTokenCache, path: Path) -> None:
    if cache.has_state_changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(cache.serialize(), encoding="utf-8")


def _build_app(client_id: str, cache: msal.SerializableTokenCache) -> msal.PublicClientApplication:
    return msal.PublicClientApplication(
        client_id,
        authority=AUTHORITY,
        token_cache=cache,
    )


def ensure_outlook_token(
    email: str,
    client_id: str,
    token_cache_path: Path,
) -> str:
    """获取有效 access token；必要时引导设备码登录。"""
    path = _cache_path(token_cache_path)
    cache = _load_cache(path)
    app = _build_app(client_id, cache)

    accounts = app.get_accounts(username=email)
    if accounts:
        result = app.acquire_token_silent(IMAP_SCOPES, account=accounts[0])
        if result and "access_token" in result:
            _save_cache(cache, path)
            return result["access_token"]

    flow = app.initiate_device_flow(scopes=IMAP_SCOPES)
    if "user_code" not in flow:
        raise RuntimeError(f"无法启动 OAuth 设备码流程: {flow}")

    print("\n" + "=" * 60)
    print("Outlook 需要 OAuth 登录（应用密码已无法用于 IMAP）")
    print(flow["message"])
    print("=" * 60 + "\n")

    result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        err = result.get("error_description") or result.get("error") or result
        raise RuntimeError(f"Outlook OAuth 登录失败: {err}")

    _save_cache(cache, path)
    logger.info("Outlook OAuth 登录成功: %s", email)
    return result["access_token"]


def get_access_token(
    email: str,
    client_id: str,
    token_cache_path: Path,
) -> str:
    path = _cache_path(token_cache_path)
    cache = _load_cache(path)
    app = _build_app(client_id, cache)

    accounts = app.get_accounts(username=email)
    if accounts:
        result = app.acquire_token_silent(IMAP_SCOPES, account=accounts[0])
        if result and "access_token" in result:
            _save_cache(cache, path)
            return result["access_token"]

    return ensure_outlook_token(email, client_id, token_cache_path)
