from __future__ import annotations

import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from dotenv import dotenv_values

from src.config import ENV_PATH, PROJECT_ROOT

ALLOWED_EXTENSIONS = {".md", ".txt"}
MAX_FILE_BYTES = 200_000


def _configured_knowledge_dir() -> Path:
    values = dotenv_values(ENV_PATH) if ENV_PATH.exists() else {}
    raw = (values.get("BUSINESS_KNOWLEDGE_DIR") or "./knowledge/aebbs").strip()
    path = Path(raw)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def knowledge_root() -> Path:
    root = _configured_knowledge_dir().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def backup_root() -> Path:
    root = knowledge_root() / ".backups"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_relpath(raw: str) -> Path:
    rel = Path(raw.strip().replace("\\", "/"))
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError("文件路径不合法")
    if not rel.name:
        raise ValueError("文件名不能为空")
    if rel.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise ValueError("只允许编辑 .md 或 .txt 文件")
    for part in rel.parts:
        if part.startswith("."):
            raise ValueError("不能编辑隐藏文件或备份目录")
        if not re.match(r"^[A-Za-z0-9._ -]+$", part):
            raise ValueError("文件名只能包含英文、数字、空格、点、横线和下划线")
    return rel


def _resolve_inside(raw: str) -> tuple[Path, str]:
    rel = _safe_relpath(raw)
    root = knowledge_root()
    path = (root / rel).resolve()
    if root not in path.parents and path != root:
        raise ValueError("文件路径越界")
    return path, rel.as_posix()


def list_rag_files() -> list[dict[str, object]]:
    root = knowledge_root()
    result: list[dict[str, object]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part.startswith(".") for part in rel.parts):
            continue
        if path.suffix.lower() not in ALLOWED_EXTENSIONS:
            continue
        stat = path.stat()
        result.append(
            {
                "path": rel.as_posix(),
                "size": stat.st_size,
                "updated_at": datetime.fromtimestamp(
                    stat.st_mtime,
                    timezone.utc,
                ).isoformat(),
            }
        )
    return result


def read_rag_file(raw_path: str) -> dict[str, object]:
    path, rel = _resolve_inside(raw_path)
    if not path.exists():
        raise FileNotFoundError(rel)
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("文件过大，无法在网页中编辑")
    return {
        "path": rel,
        "content": path.read_text(encoding="utf-8"),
    }


def _backup_file(path: Path, rel: str) -> None:
    if not path.exists():
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_name = rel.replace("/", "__")
    target = backup_root() / f"{stamp}__{safe_name}"
    shutil.copy2(path, target)


def save_rag_file(raw_path: str, content: str) -> dict[str, object]:
    encoded = content.encode("utf-8")
    max_bytes = int(os.getenv("WEB_RAG_MAX_FILE_BYTES", str(MAX_FILE_BYTES)))
    if len(encoded) > max_bytes:
        raise ValueError(f"文件内容超过限制：{max_bytes} bytes")

    path, rel = _resolve_inside(raw_path)
    _backup_file(path, rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    stat = path.stat()
    return {
        "path": rel,
        "size": stat.st_size,
        "updated_at": datetime.fromtimestamp(
            stat.st_mtime,
            timezone.utc,
        ).isoformat(),
    }
