"""The admin portal.

The portal is the human-facing half, so the tests follow a person through the flow —
connect, load the mapping, preview, approve, migrate, report — and check the two things
that matter: the migration loads exactly what the dry-run previewed, and nothing happens
without approval.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from starlette.testclient import TestClient  # noqa: E402

from firstsync.portal.app import app  # noqa: E402


@pytest.fixture(autouse=True)
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("FIRSTSYNC_STATE_DIR", str(tmp_path))


@pytest.fixture()
def client():
    return TestClient(app)


def test_index_lists_orgs(client):
    body = client.get("/").text
    assert "org_d" in body and "org_a" in body


def test_full_flow_loads_what_the_dryrun_showed(client):
    # Connect → the overview renders the access check.
    assert client.get("/org/org_d").status_code == 200
    # Load Claude's proposals, review them, preview.
    client.post("/org/org_d/seed")
    assert "contacts.email" in client.get("/org/org_d/mappings").text
    dry = client.get("/org/org_d/dryrun").text
    assert "blocking" in dry  # org_d has blocking records
    # Approve, then migrate.
    client.post("/org/org_d/approve")
    client.post("/org/org_d/migrate")
    report = client.get("/org/org_d/report").text
    # 387 loaded, exactly as the dry-run and the migration tests established.
    assert "387" in report


def test_migrate_refuses_without_approval(client):
    client.post("/org/org_a/seed")
    # Jump straight to migrate with no approval. The engine refuses; no report is written.
    client.post("/org/org_a/migrate", follow_redirects=False)
    report = client.get("/org/org_a/report").text
    assert "no migration has run" in report.lower() or "not approved" in report.lower()


def test_reset_clears_state(client):
    client.post("/org/org_a/seed")
    client.post("/org/org_a/approve")
    client.post("/org/org_a/reset")
    # After reset the org is back to "load proposals".
    assert "Load Claude's proposals" in client.get("/org/org_a").text


def test_unknown_org_is_rejected(client):
    assert client.get("/org/not_a_real_org").status_code >= 400


def test_healthz(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_data_dirs_resolve_from_env(monkeypatch):
    """The deploy scenario: the package is installed away from the orgs/ and results/
    folders, so they are located via FIRSTSYNC_ORGS_DIR and FIRSTSYNC_DEMO_RESULTS_DIR
    (as the Dockerfile sets them). The index must still list every org."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("FIRSTSYNC_ORGS_DIR", str(root / "orgs"))
    monkeypatch.setenv("FIRSTSYNC_DEMO_RESULTS_DIR", str(root / "results"))
    body = TestClient(app).get("/").text
    for org in ("org_a", "org_b", "org_c", "org_d", "org_e", "org_f"):
        assert org in body
    assert "Claude's mapping ready" in body  # demo proposals located too
