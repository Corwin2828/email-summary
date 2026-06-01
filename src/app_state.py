from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def _state_path(data_dir: Path) -> Path:
    return data_dir / "app_state.json"


def load_last_active_at(data_dir: Path) -> datetime | None:
    path = _state_path(data_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        raw = data.get("last_active_at")
        if not raw:
            return None
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (json.JSONDecodeError, ValueError, OSError):
        return None


def save_last_active_at(data_dir: Path, when: datetime | None = None) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    ts = when or datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    path = _state_path(data_dir)
    path.write_text(
        json.dumps(
            {"last_active_at": ts.astimezone(timezone.utc).isoformat()},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
