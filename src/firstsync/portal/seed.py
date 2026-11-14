"""Demo proposals, so the portal runs without an API key.

The mapping step is Claude's work and needs the agent. For a demo that a stranger can
open, we load the proposals Claude actually produced in the evaluation runs (saved under
results/) into the proposal store. They are real model output, pre-computed — not
hand-written — so the review, dry-run, approve and migrate steps downstream are genuine.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from firstsync.mapping import ProposalStore

_ENV = "FIRSTSYNC_DEMO_RESULTS_DIR"


def _results_dir() -> Path:
    override = os.environ.get(_ENV)
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[3] / "results"


def _files() -> list[Path]:
    root = _results_dir()
    return [
        root / "claude-claude-sonnet-5-5.json",
        root / "claude-claude-sonnet-5-5-held-out.json",
    ]


def demo_proposals(connection: str) -> dict[str, Any]:
    """The saved Claude proposals for one org, or KeyError if none are bundled."""
    for path in _files():
        if not path.is_file():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        org = data.get("orgs", {}).get(connection)
        if org and org.get("runs"):
            return org["runs"][0]["proposals"]
    raise KeyError(connection)


def has_demo(connection: str) -> bool:
    try:
        demo_proposals(connection)
        return True
    except KeyError:
        return False


def seed(connection: str) -> dict[str, Any]:
    """Load the bundled proposals for a connection into its proposal store."""
    proposals = demo_proposals(connection)
    ProposalStore(connection).save(proposals)
    return proposals
