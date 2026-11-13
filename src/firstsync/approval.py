"""The approval gate.

Approval is a human act, done at the command line or (later) in the portal. It is not an
MCP tool, so there is no path by which the model approves its own proposals.

An approval binds to the content of what was approved: it stores a SHA-256 of each
proposal's canonical JSON. If a proposal changes afterwards — the model proposed again,
or a file was edited — the stored hash no longer matches and the migration refuses to
run until a person approves again. Approving is cheap; migrating something nobody looked
at is not.
"""

from __future__ import annotations

import getpass
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from firstsync.config import get_settings
from firstsync.mapping import ProposalStore, target_fields


def proposal_hash(proposal: dict[str, Any]) -> str:
    canon = json.dumps(proposal, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]


def _path(connection: str) -> Path:
    return get_settings().state_dir / "approvals" / f"{connection}.json"


def load(connection: str) -> dict[str, Any] | None:
    path = _path(connection)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def approve(
    connection: str, excluded: list[str] | None = None, approved_by: str | None = None
) -> dict[str, Any]:
    """Approve the proposals as they stand right now. Returns the approval record."""
    proposals = ProposalStore(connection).load()
    if not proposals:
        raise ValueError(f"No proposals are stored for {connection!r}; nothing to approve.")
    excluded = sorted(set(excluded or []))
    unknown = [t for t in excluded if t not in target_fields()]
    if unknown:
        raise ValueError(f"Cannot exclude unknown target fields: {', '.join(unknown)}.")
    unanswered = sorted(
        t
        for t, p in proposals.items()
        if p.get("question_for_admin") and t not in excluded
    )
    record = {
        "connection": connection,
        "approved_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "approved_by": approved_by or getpass.getuser(),
        "excluded": excluded,
        "open_questions": unanswered,
        "proposal_sha256_16": {
            t: proposal_hash(p) for t, p in proposals.items() if t not in excluded
        },
    }
    path = _path(connection)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return record


def check(connection: str) -> dict[str, Any]:
    """Is the migration allowed to run? Returns {'ok': bool, 'why': ..., 'approved': ...}.

    ok is True only when an approval exists and every approved hash still matches the
    stored proposal. Targets excluded at approval time are simply not migrated.
    """
    record = load(connection)
    if record is None:
        return {
            "ok": False,
            "why": f"No approval exists for {connection!r}. Run: firstsync approve {connection}",
        }
    proposals = ProposalStore(connection).load()
    stale = sorted(
        t
        for t, digest in record["proposal_sha256_16"].items()
        if proposal_hash(proposals.get(t, {})) != digest
    )
    if stale:
        return {
            "ok": False,
            "why": (
                "Proposals changed after approval for: "
                + ", ".join(stale)
                + f". Approve again: firstsync approve {connection}"
            ),
        }
    return {"ok": True, "approved": record}
