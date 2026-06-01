from __future__ import annotations

import sqlite3
import threading
from pathlib import Path


class ProcessedStore:
    """记录已处理邮件，避免重复总结。"""

    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS processed (
                account TEXT NOT NULL,
                uid TEXT NOT NULL,
                processed_at TEXT DEFAULT (datetime('now')),
                PRIMARY KEY (account, uid)
            )
            """
        )
        self._conn.commit()

    def seen(self, account: str, uid: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM processed WHERE account = ? AND uid = ?",
                (account, uid),
            ).fetchone()
            return row is not None

    def mark(self, account: str, uid: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO processed (account, uid) VALUES (?, ?)",
                (account, uid),
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
