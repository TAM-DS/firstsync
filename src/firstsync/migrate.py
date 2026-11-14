"""The migration engine.

Runs only after a human approval (approval.check), builds every row with the same
build_row the dry-run used, and upserts into the target database. Re-running is safe by
construction: the upsert key is (tenant, external_id), so the second run of the same
data reports everything `unchanged` and writes nothing new.

What is skipped is as important as what is loaded:

    blocking        the record cannot load; its Ids go in the report
    needs_decision  an administrator has not decided yet; skipped, reported
    excluded        the whole table, when approval excluded its external_id mapping

A `warning` record loads with the warned value left out — exactly what the dry-run told
the administrator would happen.
"""

from __future__ import annotations

import json
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from firstsync import approval
from firstsync.config import get_settings
from firstsync.dryrun import SCAN_LIMIT, _split, build_row
from firstsync.mapping import ProposalStore
from firstsync.salesforce import ObjectNotAccessible, SalesforceClient
from firstsync.salesforce.rest import UNSAMPLED_TYPES
from firstsync.target import TARGET_SCHEMA
from firstsync.target.db import TargetDB, tenant_id


class TableMigration(BaseModel):
    table: str
    source_object: str | None = None
    read: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped_blocking: list[str] = Field(default_factory=list)
    skipped_needs_decision: list[str] = Field(default_factory=list)
    warnings: int = 0
    not_runnable: str | None = None


class Migration(BaseModel):
    run_id: str
    connection: str
    tenant_id: str
    started_at: str
    approved_by: str
    approved_at: str
    status: Literal["completed", "refused"]
    refused_because: str | None = None
    tables: list[TableMigration] = Field(default_factory=list)

    def totals(self) -> dict[str, int]:
        c: Counter[str] = Counter()
        for t in self.tables:
            c.update(
                read=t.read,
                inserted=t.inserted,
                updated=t.updated,
                unchanged=t.unchanged,
                skipped=len(t.skipped_blocking) + len(t.skipped_needs_decision),
            )
        return dict(c)


def run_migration(
    client: SalesforceClient,
    connection: str,
    db: TargetDB,
    limit: int = SCAN_LIMIT,
) -> Migration:
    """The only entry point. Refuses without a valid, current human approval."""
    gate = approval.check(connection)
    base: dict[str, Any] = dict(
        run_id=uuid.uuid4().hex[:12],
        connection=connection,
        tenant_id=tenant_id(connection),
        started_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    if not gate["ok"]:
        return Migration(
            **base, approved_by="", approved_at="", status="refused",
            refused_because=gate["why"],
        )
    record = gate["approved"]
    migration = Migration(
        **base,
        approved_by=record["approved_by"],
        approved_at=record["approved_at"],
        status="completed",
    )
    proposals = ProposalStore(connection).load()
    excluded = set(record["excluded"])
    tenant = migration.tenant_id

    for table, spec in TARGET_SCHEMA["tables"].items():
        fields = {f["name"]: {**f, "_table": table} for f in spec["fields"]}
        mapped = {
            name: (None if f"{table}.{name}" in excluded else proposals.get(f"{table}.{name}"))
            for name in fields
        }
        source_object, _ = _split((mapped["external_id"] or {}).get("source"))
        result = TableMigration(table=table, source_object=source_object)
        migration.tables.append(result)
        if source_object is None:
            result.not_runnable = (
                "No approved source for external_id, so no record can be migrated."
            )
            continue
        try:
            describe = client.describe(source_object)
        except ObjectNotAccessible as exc:
            result.not_runnable = str(exc)
            continue
        names = [f["name"] for f in describe["fields"] if f.get("type") not in UNSAMPLED_TYPES]
        for record_ in client.sample(source_object, names, limit):
            result.read += 1
            record_id = str(record_.get("Id"))
            row, status, _issues = build_row(record_, fields, mapped, source_object)
            if status == "blocking":
                result.skipped_blocking.append(record_id)
                continue
            if status == "needs_decision":
                result.skipped_needs_decision.append(record_id)
                continue
            if status == "warning":
                result.warnings += 1
            outcome = db.upsert(table, tenant, row)
            setattr(result, outcome, getattr(result, outcome) + 1)
        db.commit()

    save(migration)
    return migration


# --- storage ----------------------------------------------------------------------------


def _folder(connection: str) -> Path:
    return get_settings().state_dir / "migrations" / connection


def save(migration: Migration) -> Path:
    folder = _folder(migration.connection)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{migration.run_id}.json"
    path.write_text(migration.model_dump_json(indent=2) + "\n", encoding="utf-8")
    (folder / "latest").write_text(migration.run_id, encoding="utf-8")
    return path


def load(connection: str, run_id: str | None = None) -> Migration:
    folder = _folder(connection)
    if run_id is None:
        pointer = folder / "latest"
        if not pointer.is_file():
            raise ValueError(f"No migration has been run for {connection!r}.")
        run_id = pointer.read_text(encoding="utf-8").strip()
    if not run_id.isalnum():
        raise ValueError("Not a valid migration run id.")
    path = folder / f"{run_id}.json"
    if not path.is_file():
        raise ValueError(f"No migration {run_id!r} for {connection!r}.")
    return Migration.model_validate(json.loads(path.read_text(encoding="utf-8")))


def status_summary(migration: Migration) -> dict[str, Any]:
    """What the model may see: counts and reasons, read-only."""
    return {
        "run_id": migration.run_id,
        "status": migration.status,
        "refused_because": migration.refused_because,
        "started_at": migration.started_at,
        "approved_by": migration.approved_by,
        "totals": migration.totals(),
        "tables": [t.model_dump() for t in migration.tables],
        "note": (
            "Migration runs only after human approval at the CLI; there is no tool that "
            "starts it. Skipped record Ids are listed so the administrator can fix and "
            "re-run; re-running never duplicates."
        ),
    }
