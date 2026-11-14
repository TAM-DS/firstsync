"""The trace view over the audit log."""

from __future__ import annotations

import json

import pytest

from firstsync import audit, trace


@pytest.fixture(autouse=True)
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("FIRSTSYNC_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("FIRSTSYNC_AUDIT_LOG", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("FIRSTSYNC_RUN_ID", "run_aaaa")


def test_empty_log_is_not_an_error():
    assert trace.read_entries() == []
    assert trace.runs() == []
    assert "No audit entries" in trace.render_list([])


def test_groups_calls_by_run(monkeypatch):
    audit.record(tool="sf_describe_object", stage="discover", connection="org_b",
                 args={}, result={"x": 1})
    audit.record(tool="mapping_propose", stage="map", connection="org_b", args={}, result={})
    monkeypatch.setenv("FIRSTSYNC_RUN_ID", "run_bbbb")
    audit.record(tool="rule_test", stage="map", connection="org_c", args={}, error="boom")

    all_runs = trace.runs()
    assert len(all_runs) == 2
    by_id = {t.run_id: t for t in all_runs}
    assert by_id["run_aaaa"].calls == 2
    assert by_id["run_aaaa"].failures == 0
    assert by_id["run_aaaa"].tools == {"mapping_propose": 1, "sf_describe_object": 1}
    assert by_id["run_bbbb"].failures == 1
    assert by_id["run_bbbb"].errors[0]["error"] == "boom"


def test_filter_by_connection():
    audit.record(tool="t1", stage="s", connection="org_b", args={}, result={})
    audit.record(tool="t2", stage="s", connection="org_c", args={}, result={})
    only_b = trace.runs(connection="org_b")
    assert sum(t.calls for t in only_b) == 1
    assert only_b[0].connections == ["org_b"]


def test_one_run_detail_and_missing():
    audit.record(tool="sf_count_records", stage="discover", connection="org_b",
                 args={}, result={})
    t = trace.one("run_aaaa")
    assert t.calls == 1
    assert "sf_count_records" in trace.render_run(t)
    with pytest.raises(ValueError):
        trace.one("run_nope")


def test_malformed_lines_are_skipped(tmp_path):
    path = tmp_path / "audit.jsonl"
    path.write_text(
        json.dumps({"run_id": "r", "tool": "t", "ts": "2026-01-01T00:00:00+00:00", "ok": True})
        + "\nnot json\n\n",
        encoding="utf-8",
    )
    entries = trace.read_entries(path)
    assert len(entries) == 1
