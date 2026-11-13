"""The dry-run engine: deterministic, read-only, and honest about what it found."""

from __future__ import annotations

import json

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from firstsync import dryrun
from firstsync.connections import get_client
from firstsync.dryrun import DryRun, run_dry_run


def proposals_for(org: str) -> dict:
    """A handwritten, correct proposal set for the generated orgs' common shape."""
    path = "results/claude-claude-sonnet-5-5.json"
    data = json.load(open(path, encoding="utf-8"))
    return data["orgs"][org]["runs"][0]["proposals"]


@pytest.fixture()
def org_d() -> DryRun:
    return run_dry_run(get_client("org_d"), "org_d", proposals_for("org_d"), limit=2000)


def test_finds_the_planted_defects(org_d: DryRun) -> None:
    by = {(g.target, g.severity): g for g in org_d.groups}
    # Org D was generated with contacts missing emails, deals missing amounts,
    # truncated phone numbers, and duplicated contacts. The dry-run must find all four.
    assert by[("contacts.email", "blocking")].count == 5
    assert by[("deals.amount", "blocking")].count == 4
    assert by[("contacts.phone", "warning")].count == 3
    assert len(org_d.duplicates) == 6
    assert all(d.table == "contacts" for d in org_d.duplicates)


def test_counts_add_up(org_d: DryRun) -> None:
    for t in org_d.tables:
        assert t.clean + t.warning + t.needs_decision + t.blocking == t.records
        assert t.dead_lettered == 0


def test_is_deterministic(org_d: DryRun) -> None:
    again = run_dry_run(get_client("org_d"), "org_d", proposals_for("org_d"), limit=2000)
    strip = {"run_id", "started_at"}
    assert org_d.model_dump(exclude=strip) == again.model_dump(exclude=strip)


def test_writes_nothing_and_says_so(org_d: DryRun) -> None:
    assert org_d.wrote_anything is False
    assert dryrun.summary(org_d)["wrote_anything"] is False


def test_failure_examples_are_masked(org_d: DryRun) -> None:
    text = json.dumps([g.model_dump() for g in org_d.groups])
    # No real name, email domain, or full phone number may appear in failure output.
    assert "@example" not in text.lower()
    for g in org_d.groups:
        if isinstance(g.example_input, str) and "@" in g.example_input:
            assert set(g.example_input.split("@")[0]) <= set("x.0123456789")


def test_group_ids_capped(org_d: DryRun) -> None:
    for g in org_d.groups:
        assert len(g.record_ids) <= dryrun.MAX_IDS_PER_GROUP
        assert g.count >= len(g.record_ids)


def test_clean_org_is_clean() -> None:
    result = run_dry_run(get_client("org_a"), "org_a", proposals_for("org_a"), limit=2000)
    assert sum(t.blocking for t in result.tables) == 0


def test_unmapped_picklist_needs_a_decision() -> None:
    result = run_dry_run(get_client("org_b"), "org_b", proposals_for("org_b"), limit=2000)
    g = next(g for g in result.groups if g.target == "deals.stage")
    assert g.severity == "needs_decision"
    assert g.count == 15


def test_save_and_load_roundtrip(tmp_path, monkeypatch, org_d: DryRun) -> None:
    monkeypatch.setenv("FIRSTSYNC_STATE_DIR", str(tmp_path))
    path = dryrun.save(org_d)
    assert path.is_file()
    loaded = dryrun.load("org_d")
    assert loaded == org_d
    assert dryrun.load("org_d", org_d.run_id) == org_d
    with pytest.raises(ValueError):
        dryrun.load("org_d", "../../etc/passwd")
    with pytest.raises(ValueError):
        dryrun.load("org_never_ran")


def test_start_requires_proposals(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FIRSTSYNC_STATE_DIR", str(tmp_path))
    with pytest.raises(ValueError, match="No mapping proposals"):
        dryrun.start(get_client("org_a"), "org_a")


# --- property-based: rerunning never changes the verdict (idempotence) -----------------


@settings(max_examples=25, deadline=None)
@given(limit=st.integers(min_value=1, max_value=200))
def test_any_limit_is_safe_and_idempotent(limit: int) -> None:
    client = get_client("org_d")
    props = proposals_for("org_d")
    strip = {"run_id", "started_at"}
    first = run_dry_run(client, "org_d", props, limit=limit)
    second = run_dry_run(client, "org_d", props, limit=limit)
    assert first.model_dump(exclude=strip) == second.model_dump(exclude=strip)
    for t in first.tables:
        assert t.records <= limit
        assert t.clean + t.warning + t.needs_decision + t.blocking == t.records
