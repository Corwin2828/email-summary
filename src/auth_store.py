from __future__ import annotations

import getpass
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash

from src.config import PROJECT_ROOT, resolve_data_dir

ROLES = {"owner", "team"}


@dataclass(frozen=True)
class WebUser:
    username: str
    role: str


def users_path(data_dir: Path | None = None) -> Path:
    return (data_dir or resolve_data_dir()) / "web_users.json"


def session_secret_path(data_dir: Path | None = None) -> Path:
    return (data_dir or resolve_data_dir()) / "web_session_secret"


def load_session_secret(data_dir: Path | None = None) -> str:
    path = session_secret_path(data_dir)
    if path.exists():
        raw = path.read_text(encoding="utf-8").strip()
        if raw:
            return raw
    path.parent.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_urlsafe(48)
    path.write_text(secret + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return secret


def _load_raw(path: Path) -> dict:
    if not path.exists():
        return {"users": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"users": {}}
    if not isinstance(data, dict):
        return {"users": {}}
    users = data.get("users")
    if not isinstance(users, dict):
        data["users"] = {}
    return data


def _write_raw(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    try:
        path.chmod(0o600)
    except OSError:
        pass


def list_users(data_dir: Path | None = None) -> list[dict[str, str]]:
    data = _load_raw(users_path(data_dir))
    result: list[dict[str, str]] = []
    for username, info in sorted(data.get("users", {}).items()):
        if not isinstance(info, dict):
            continue
        role = info.get("role", "")
        if role in ROLES:
            result.append({"username": username, "role": role})
    return result


def set_user_password(
    username: str,
    password: str,
    role: str,
    data_dir: Path | None = None,
) -> None:
    username = username.strip()
    if not username:
        raise ValueError("用户名不能为空")
    if role not in ROLES:
        raise ValueError(f"角色必须是: {', '.join(sorted(ROLES))}")
    if len(password) < 10:
        raise ValueError("密码至少需要 10 个字符")

    path = users_path(data_dir)
    data = _load_raw(path)
    data.setdefault("users", {})[username] = {
        "role": role,
        "password_hash": generate_password_hash(password),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_raw(path, data)


def verify_user(
    username: str,
    password: str,
    data_dir: Path | None = None,
) -> WebUser | None:
    data = _load_raw(users_path(data_dir))
    info = data.get("users", {}).get(username.strip())
    if not isinstance(info, dict):
        return None
    role = info.get("role", "")
    password_hash = info.get("password_hash", "")
    if role not in ROLES or not password_hash:
        return None
    if not check_password_hash(password_hash, password):
        return None
    return WebUser(username=username.strip(), role=role)


def bootstrap_default_users(data_dir: Path | None = None) -> None:
    existing = {u["username"] for u in list_users(data_dir)}
    for username, role in (("owner", "owner"), ("team", "team")):
        if username in existing:
            continue
        while True:
            password = getpass.getpass(f"Set password for {username} ({role}): ")
            confirm = getpass.getpass("Confirm password: ")
            if password != confirm:
                print("Passwords do not match. Try again.")
                continue
            set_user_password(username, password, role, data_dir)
            break


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Manage web admin users")
    sub = parser.add_subparsers(dest="cmd", required=True)

    set_pw = sub.add_parser("set-password", help="Set or reset a user's password")
    set_pw.add_argument("username")
    set_pw.add_argument("--role", choices=sorted(ROLES), required=True)

    sub.add_parser("list", help="List configured users")
    sub.add_parser("bootstrap", help="Create owner/team users if missing")

    args = parser.parse_args()
    data_dir = resolve_data_dir()
    if args.cmd == "set-password":
        password = getpass.getpass(f"Set password for {args.username}: ")
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            raise SystemExit("Passwords do not match")
        set_user_password(args.username, password, args.role, data_dir)
        print(f"Updated {args.username} ({args.role}) at {users_path(data_dir)}")
    elif args.cmd == "list":
        for user in list_users(data_dir):
            print(f"{user['username']}\t{user['role']}")
    elif args.cmd == "bootstrap":
        bootstrap_default_users(data_dir)
        print(f"Users stored at {users_path(data_dir)}")


if __name__ == "__main__":
    main()
