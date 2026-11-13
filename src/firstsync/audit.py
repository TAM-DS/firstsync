"""Append-only log of every tool call.

Each line records what was asked and a hash of what was returned, so a reviewer can
confirm which evidence a proposal was built on without storing the evidence twice.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_PATH = ".firstsync/audit.jsonl"


def log_path() -> Path:
    return Path(os.environ.get("FIRSTSYNC_AUDIT_LOG", DEFAULT_PATH))


def output_hash(result: Any) -> str:
    canonical = json.dumps(result, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def record(
    *,
    tool: str,
    stage: str,
    connection: str | None,
    args: dict[str, Any],
    result: Any = None,
    error: str | None = None,
) -> dict[str, Any]:
    entry = {
        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
        "tool": tool,
        "stage": stage,
        "connection": connection,
        "args": args,
        "ok": error is None,
        "output_sha256": output_hash(result) if error is None else None,
        "error": error,
    }
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")
    return entry
