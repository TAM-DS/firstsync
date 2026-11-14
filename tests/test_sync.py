"""The sync engine and the go-live report.

Sync is tested by mutating a source and watching the target follow — but only in the
safe direction. The fixture client holds a reference to its objects dict, so changing the
dict between runs is exactly a source that changed between syncs.
"""

from __future__ import annotations

import copy
import json

import pytest

from firstsync import approval, dryrun, golive, migrate, sync
from firstsync.connections import orgs_dir
from firstsync.mapping import ProposalStore
from firstsync.salesforce import FixtureSalesforceClient
from firstsync.target.db import TargetDB, tenant_id


def proposals_for(org: str) -> dict:
    data = json.load(open("results/claude-claude-sonnet-5-5.json", encoding="utf-8"))
    return data["orgs"][org]["runs"][0]["proposals"]


@pytest.fixture(autouse=True)
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("FIRSTSYNC_STATE_DIR", str(tmp_path))


@pytest.fixture()
def world(tmp_path):
    """A mutable org_d, approved, already migrated into a fresh SQLite db."""
    fixture = json.loads((orgs_dir() / "org_d" / "fixture.json").read_text())
    fixture = copy.deepcopy(fixture)
    client = FixtureSalesforceClient(fixture)
    ProposalStore("org_d").save(proposals_for("org_d"))
    dryrun.start(client, "org_d")  # the admin previews before approving
    approval.approve("org_d", approved_by="test")
    db = TargetDB(str(tmp_path / "t.db"))
    migrate.run_migration(client, "org_d", db)
    return client, db, fixture


def contacts(fixture: dict) -> list[dict]:
    return fixture["objects"]["Contact"]["records"]


def a_clean_contact(fixture: dict) -> dict:
    """A contact that migrated cleanly (has an email)."""
    return next(c for c in contacts(fixture) if c.get("Email"))


def test_no_change_means_all_unchanged(world):
    client, db, _ = world
    result = sync.run_sync(client, "org_d", db)
    assert result.status == "completed"
    t = result.totals()
    assert t["added"] == 0 and t["changed"] == 0
    assert t["regressed"] == 0 and t["vanished"] == 0
    assert t["unchanged"] > 0
    assert result.needs_attention() is False


def test_new_source_record_is_added(world):
    client, db, fixture = world
    before = db.count("contacts", tenant_id("org_d"))
    contacts(fixture).append({
        "Id": "003000000000999AAA", "AccountId": "001000000000001AAA",
        "FirstName": "New", "LastName": "Person", "Email": "new.person@acme.example",
        "Phone": "+15125550199", "Department": "Billing",
    })
    result = sync.run_sync(client, "org_d", db)
    added = next(t for t in result.tables if t.table == "contacts").added
    assert added == 1
    assert db.count("contacts", tenant_id("org_d")) == before + 1


def test_changed_source_record_is_updated(world):
    client, db, fixture = world
    target = a_clean_contact(fixture)
    target["FirstName"] = "Renamed"
    result = sync.run_sync(client, "org_d", db)
    contacts_sync = next(t for t in result.tables if t.table == "contacts")
    assert contacts_sync.changed == 1
    assert contacts_sync.added == 0


def test_vanished_record_is_reported_never_deleted(world):
    client, db, fixture = world
    before = db.count("contacts", tenant_id("org_d"))
    victim = a_clean_contact(fixture)
    victim_id = victim["Id"]
    contacts(fixture).remove(victim)
    result = sync.run_sync(client, "org_d", db)
    contacts_sync = next(t for t in result.tables if t.table == "contacts")
    assert victim_id in contacts_sync.vanished
    # Reported, not deleted: the row is still in the target.
    assert db.count("contacts", tenant_id("org_d")) == before
    assert victim_id in db.external_ids("contacts", tenant_id("org_d"))
    assert result.needs_attention() is True


def test_regressed_record_is_flagged_and_left_intact(world):
    client, db, fixture = world
    target = a_clean_contact(fixture)
    target_id = target["Id"]
    target["Email"] = None  # a required field, blanked at the source
    result = sync.run_sync(client, "org_d", db)
    contacts_sync = next(t for t in result.tables if t.table == "contacts")
    assert target_id in contacts_sync.regressed
    # The good target row is untouched — onboarding does not blank a live record.
    assert target_id in db.external_ids("contacts", tenant_id("org_d"))
    assert result.needs_attention() is True


def test_sync_refuses_without_approval(tmp_path):
    fixture = json.loads((orgs_dir() / "org_d" / "fixture.json").read_text())
    client = FixtureSalesforceClient(fixture)
    ProposalStore("org_d").save(proposals_for("org_d"))
    db = TargetDB(str(tmp_path / "t.db"))
    result = sync.run_sync(client, "org_d", db)
    assert result.status == "refused"
    assert "approval" in (result.refused_because or "").lower()


def test_sync_is_idempotent(world):
    client, db, _ = world
    first = sync.run_sync(client, "org_d", db)
    second = sync.run_sync(client, "org_d", db)
    assert first.totals()["unchanged"] == second.totals()["unchanged"]
    assert second.totals()["added"] == 0 and second.totals()["changed"] == 0


def test_save_and_load_roundtrip(world):
    client, db, _ = world
    result = sync.run_sync(client, "org_d", db)
    assert sync.load("org_d") == result
    assert sync.load("org_d", result.run_id) == result
    with pytest.raises(ValueError):
        sync.load("org_d", "../escape")


# --- go-live report ---------------------------------------------------------------------


def test_report_reflects_the_full_onboarding(world):
    client, db, fixture = world
    sync.run_sync(client, "org_d", db)
    report = golive.build("org_d")
    assert report["approved"]["by"] == "test"
    assert report["migration"]["inserted"] == 387
    assert report["latest_sync"] is not None
    # org_d's dry-run has blocking records and the approval has open questions.
    assert any("cannot load" in item for item in report["open_items"])
    assert any("open question" in item for item in report["open_items"])
    text = golive.render(report)
    assert "Onboarding: org_d" in text
    assert "live" in report["headline"]


def test_report_before_approval_says_so():
    ProposalStore("org_d").save(proposals_for("org_d"))
    report = golive.build("org_d")
    assert report["approved"] is None
    assert "Not approved" in report["headline"]


def test_report_flags_sync_attention(world):
    client, db, fixture = world
    contacts(fixture).remove(a_clean_contact(fixture))
    sync.run_sync(client, "org_d", db)
    report = golive.build("org_d")
    assert "attention" in report["headline"]
    assert any("vanished" in item for item in report["open_items"])
