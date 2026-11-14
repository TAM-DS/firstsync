"""The approval gate and the migration engine.

The properties that matter:
  - no approval, no migration — ever
  - a changed proposal invalidates the approval that covered it
  - the migration loads exactly what the dry-run said it would
  - re-running changes nothing (idempotent by upsert key)
"""

from __future__ import annotations

import json

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from firstsync import approval, migrate
from firstsync.connections import get_client
from firstsync.dryrun import run_dry_run
from firstsync.mapping import ProposalStore
from firstsync.target.db import TargetDB, ddl, tenant_id


def proposals_for(org: str) -> dict:
    data = json.load(open("results/claude-claude-sonnet-5-5.json", encoding="utf-8"))
    return data["orgs"][org]["runs"][0]["proposals"]


@pytest.fixture(autouse=True)
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("FIRSTSYNC_STATE_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture()
def org_d_approved():
    ProposalStore("org_d").save(proposals_for("org_d"))
    approval.approve("org_d", approved_by="test-admin")
    return get_client("org_d")


# --- the gate ---------------------------------------------------------------------------


def test_no_approval_no_migration():
    ProposalStore("org_d").save(proposals_for("org_d"))
    db = TargetDB(":memory:")
    result = migrate.run_migration(get_client("org_d"), "org_d", db)
    assert result.status == "refused"
    assert "No approval" in (result.refused_because or "")
    assert db.count("contacts", tenant_id("org_d")) == 0


def test_changed_proposal_invalidates_approval(org_d_approved):
    props = ProposalStore("org_d").load()
    props["contacts.email"] = {**props["contacts.email"], "source": "Contact.Phone"}
    ProposalStore("org_d").save(props)
    db = TargetDB(":memory:")
    result = migrate.run_migration(org_d_approved, "org_d", db)
    assert result.status == "refused"
    assert "contacts.email" in (result.refused_because or "")
    assert db.count("contacts", tenant_id("org_d")) == 0


def test_approve_requires_proposals():
    with pytest.raises(ValueError, match="No proposals"):
        approval.approve("org_never")


def test_approve_rejects_unknown_exclusion():
    ProposalStore("org_d").save(proposals_for("org_d"))
    with pytest.raises(ValueError, match="unknown target"):
        approval.approve("org_d", excluded=["contacts.nonsense"])


def test_approval_records_open_questions():
    ProposalStore("org_d").save(proposals_for("org_d"))
    record = approval.approve("org_d")
    asked = {
        t for t, p in proposals_for("org_d").items() if p.get("question_for_admin")
    }
    assert set(record["open_questions"]) == asked


# --- the migration ----------------------------------------------------------------------


def test_migration_matches_the_dry_run(org_d_approved):
    props = ProposalStore("org_d").load()
    dry = run_dry_run(org_d_approved, "org_d", props, limit=2000)
    db = TargetDB(":memory:")
    result = migrate.run_migration(org_d_approved, "org_d", db)
    assert result.status == "completed"
    by_table = {t.table: t for t in result.tables}
    for d in dry.tables:
        m = by_table[d.table]
        # Loaded = clean + warning; skipped = blocking + needs_decision. Exactly.
        assert m.inserted == d.clean + d.warning
        assert len(m.skipped_blocking) == d.blocking
        assert len(m.skipped_needs_decision) == d.needs_decision
        assert m.warnings == d.warning
        assert db.count(d.table, tenant_id("org_d")) == m.inserted


def test_migration_is_idempotent(org_d_approved):
    db = TargetDB(":memory:")
    first = migrate.run_migration(org_d_approved, "org_d", db)
    second = migrate.run_migration(org_d_approved, "org_d", db)
    assert first.totals()["inserted"] > 0
    assert second.totals()["inserted"] == 0
    assert second.totals()["updated"] == 0
    assert second.totals()["unchanged"] == first.totals()["inserted"]
    for t in first.tables:
        assert db.count(t.table, tenant_id("org_d")) == t.inserted


def test_excluded_table_is_not_migrated():
    ProposalStore("org_d").save(proposals_for("org_d"))
    approval.approve("org_d", excluded=["activities.external_id"])
    db = TargetDB(":memory:")
    result = migrate.run_migration(get_client("org_d"), "org_d", db)
    activities = next(t for t in result.tables if t.table == "activities")
    assert activities.not_runnable is not None
    assert db.count("activities", tenant_id("org_d")) == 0
    assert db.count("accounts", tenant_id("org_d")) > 0


def test_save_and_load_roundtrip(org_d_approved):
    db = TargetDB(":memory:")
    result = migrate.run_migration(org_d_approved, "org_d", db)
    assert migrate.load("org_d") == result
    assert migrate.load("org_d", result.run_id) == result
    with pytest.raises(ValueError):
        migrate.load("org_d", "../escape")
    summary = migrate.status_summary(result)
    assert summary["totals"]["inserted"] == 387


# --- the database -----------------------------------------------------------------------


def test_ddl_covers_every_table():
    statements = ddl()
    assert len(statements) == 4
    assert all("UNIQUE (tenant_id, external_id)" in s for s in statements)


def test_upsert_outcomes():
    db = TargetDB(":memory:")
    row = {"external_id": "x1", "name": "Acme", "industry": None, "tier": None,
           "website": None, "customer_since": None, "owner_email": None}
    tenant = tenant_id("t")
    assert db.upsert("accounts", tenant, row) == "inserted"
    assert db.upsert("accounts", tenant, row) == "unchanged"
    assert db.upsert("accounts", tenant, {**row, "industry": "software"}) == "updated"
    assert db.count("accounts", tenant) == 1
    with pytest.raises(ValueError):
        db.upsert("nonsense", tenant, row)


def test_tenants_are_isolated():
    db = TargetDB(":memory:")
    row = {"external_id": "x1", "name": "Acme", "industry": None, "tier": None,
           "website": None, "customer_since": None, "owner_email": None}
    db.upsert("accounts", tenant_id("a"), row)
    db.upsert("accounts", tenant_id("b"), row)
    assert db.count("accounts", tenant_id("a")) == 1
    assert db.count("accounts", tenant_id("b")) == 1


# --- property-based ---------------------------------------------------------------------


@settings(max_examples=15, deadline=None)
@given(runs=st.integers(min_value=2, max_value=4), limit=st.integers(min_value=10, max_value=300))
def test_n_runs_equal_one_run(tmp_path_factory, runs: int, limit: int) -> None:
    import os

    tmp = tmp_path_factory.mktemp("state")
    os.environ["FIRSTSYNC_STATE_DIR"] = str(tmp)
    ProposalStore("org_d").save(proposals_for("org_d"))
    approval.approve("org_d", approved_by="prop")
    client = get_client("org_d")
    db = TargetDB(":memory:")
    results = [migrate.run_migration(client, "org_d", db, limit) for _ in range(runs)]
    inserted = results[0].totals()["inserted"]
    for later in results[1:]:
        assert later.totals()["inserted"] == 0
        assert later.totals()["unchanged"] == inserted
    for t in results[0].tables:
        assert db.count(t.table, tenant_id("org_d")) == t.inserted
