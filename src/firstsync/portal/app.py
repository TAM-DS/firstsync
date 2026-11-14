"""The FastAPI portal.

Linear flow, server-rendered, no model calls: connect → review mappings → dry-run preview
→ approve → migrate → report. Each action is a plain POST that calls an engine and
redirects, so the browser's back button and refresh behave and nothing needs JavaScript.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from firstsync import approval, dryrun, golive, migrate, sync, tools
from firstsync.config import get_settings
from firstsync.connections import UnknownConnection, available_fixtures, get_client
from firstsync.mapping import ProposalStore, coverage
from firstsync.portal import seed
from firstsync.target.db import TargetDB

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

app = FastAPI(title="FirstSync", docs_url=None, redoc_url=None)


@app.exception_handler(UnknownConnection)
def _unknown_connection(request: Request, exc: UnknownConnection) -> PlainTextResponse:
    return PlainTextResponse(f"No such connection: {exc}", status_code=404)


def _db_path(connection: str) -> Path:
    folder = get_settings().state_dir / "portal"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{connection}.db"


def _page(request: Request, name: str, **ctx: Any) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(request, name, ctx)


def _known(connection: str) -> str:
    if connection not in available_fixtures():
        raise UnknownConnection(connection)
    return connection


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    orgs = [
        {"name": c, "has_demo": seed.has_demo(c), "approved": approval.load(c) is not None}
        for c in available_fixtures()
    ]
    return _page(request, "index.html", orgs=orgs)


@app.get("/org/{connection}", response_class=HTMLResponse)
def overview(request: Request, connection: str) -> HTMLResponse:
    _known(connection)
    client = get_client(connection)
    access = tools.sf_check_access(client)
    proposals = ProposalStore(connection).load()
    gate = approval.check(connection) if proposals else {"ok": False}
    return _page(
        request,
        "org.html",
        connection=connection,
        access=access,
        has_proposals=bool(proposals),
        has_demo=seed.has_demo(connection),
        coverage=coverage(proposals) if proposals else None,
        approved=gate.get("ok", False),
        step=_step(connection, bool(proposals), gate.get("ok", False)),
    )


def _step(connection: str, has_proposals: bool, approved: bool) -> str:
    try:
        migrate.load(connection)
        return "migrated"
    except ValueError:
        pass
    if approved:
        return "approved"
    if has_proposals:
        return "mapped"
    return "start"


@app.post("/org/{connection}/seed")
def do_seed(connection: str) -> RedirectResponse:
    _known(connection)
    seed.seed(connection)
    return RedirectResponse(f"/org/{connection}/mappings", status_code=303)


@app.get("/org/{connection}/mappings", response_class=HTMLResponse)
def mappings(request: Request, connection: str) -> HTMLResponse:
    _known(connection)
    proposals = ProposalStore(connection).load()
    rows = sorted(proposals.values(), key=lambda p: p["target"])
    return _page(
        request,
        "mappings.html",
        connection=connection,
        rows=rows,
        coverage=coverage(proposals),
    )


@app.get("/org/{connection}/dryrun", response_class=HTMLResponse)
def dry_run(request: Request, connection: str) -> HTMLResponse:
    _known(connection)
    result = dryrun.start(get_client(connection), connection, limit=2000)
    return _page(
        request,
        "dryrun.html",
        connection=connection,
        tables=result.tables,
        groups=result.groups,
        duplicates=result.duplicates,
        preview=result.preview,
        approved=approval.check(connection).get("ok", False),
    )


@app.post("/org/{connection}/approve")
def do_approve(connection: str) -> RedirectResponse:
    _known(connection)
    approval.approve(connection, approved_by="portal demo admin")
    return RedirectResponse(f"/org/{connection}", status_code=303)


@app.post("/org/{connection}/migrate")
def do_migrate(connection: str) -> RedirectResponse:
    _known(connection)
    db = TargetDB(_db_path(connection))
    try:
        migrate.run_migration(get_client(connection), connection, db, limit=2000)
    finally:
        db.close()
    return RedirectResponse(f"/org/{connection}/report", status_code=303)


@app.post("/org/{connection}/sync")
def do_sync(connection: str) -> RedirectResponse:
    _known(connection)
    db = TargetDB(_db_path(connection))
    try:
        sync.run_sync(get_client(connection), connection, db, limit=2000)
    finally:
        db.close()
    return RedirectResponse(f"/org/{connection}/report", status_code=303)


@app.get("/org/{connection}/report", response_class=HTMLResponse)
def report(request: Request, connection: str) -> HTMLResponse:
    _known(connection)
    return _page(request, "report.html", connection=connection, report=golive.build(connection))


@app.post("/org/{connection}/reset")
def do_reset(connection: str) -> RedirectResponse:
    _known(connection)
    ProposalStore(connection).clear()
    settings = get_settings()
    for sub in ("approvals", "dryruns", "migrations", "syncs"):
        _wipe(settings.state_dir / sub / connection, settings.state_dir / sub, connection)
    _db_path(connection).unlink(missing_ok=True)
    return RedirectResponse(f"/org/{connection}", status_code=303)


def _wipe(folder: Path, parent: Path, connection: str) -> None:
    import shutil

    if folder.is_dir():
        shutil.rmtree(folder, ignore_errors=True)
    single = parent / f"{connection}.json"
    single.unlink(missing_ok=True)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(get_settings().portal_port))  # noqa: S104


if __name__ == "__main__":
    main()
