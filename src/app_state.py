from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def _state_path(data_dir: Path) -> Path:
    return data_dir / "app_state.json"


def _parse_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def load_last_active_at(data_dir: Path, account: str | None = None) -> datetime | None:
    path = _state_path(data_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if account:
            account_state = data.get("accounts", {}).get(account, {})
            dt = _parse_dt(account_state.get("last_active_at"))
            if dt:
                return dt
        return _parse_dt(data.get("last_active_at"))
    except (json.JSONDecodeError, ValueError, OSError):
        return None


def save_last_active_at(
    data_dir: Path,
    when: datetime | None = None,
    account: str | None = None,
) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    ts = when or datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    path = _state_path(data_dir)
    raw: dict = {}
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            raw = {}

    iso = ts.astimezone(timezone.utc).isoformat()
    raw["last_active_at"] = iso
    if account:
        accounts = raw.setdefault("accounts", {})
        accounts.setdefault(account, {})["last_active_at"] = iso

    path.write_text(
        json.dumps(raw, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
