from __future__ import annotations

import pytest

from firstsync.connections import get_client


@pytest.fixture(autouse=True)
def _audit_to_tmp(tmp_path, monkeypatch):
    monkeypatch.setenv("FIRSTSYNC_AUDIT_LOG", str(tmp_path / "audit.jsonl"))
    monkeypatch.delenv("FIRSTSYNC_ORGS_DIR", raising=False)
    monkeypatch.delenv("FIRSTSYNC_MAX_TOOL_CALLS", raising=False)
    monkeypatch.setattr("firstsync.mcp_server._calls", 0)
    return tmp_path / "audit.jsonl"


@pytest.fixture
def org_a():
    return get_client("org_a")


@pytest.fixture
def org_b():
    return get_client("org_b")
