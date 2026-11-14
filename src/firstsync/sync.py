"""The sync engine.

A migration is a one-time event; onboarding does not end when it finishes. Source data
keeps changing — new contacts, edited accounts, deals that close — and the target has to
keep up. Sync is the ongoing half: re-read the source, rebuild every row with the same
`build_row` the dry-run and migration used, and apply only what changed.

It runs behind the same approval gate as the migration: the mapping is what a person
approved, and sync does not change the mapping, so the approval still holds. Sync changes
*data*, and only in the safe direction — it inserts new records and updates changed ones.
It never deletes and never overwrites a good row with a broken one. Two situations call
for a human, so sync reports them and touches nothing:

    regressed   a record that loaded cleanly at go-live now fails validation in the
                source (someone blanked a required field). The good target row is left
                as it is; nobody wants onboarding to blank a live record.
    vanished    a record in the target is no longer in the source. It may have been
                deleted, or merged, or simply fallen out of the query. Deleting in the
                target is a decision for the administrator, not for sync.

Everything sync does is deterministic and idempotent: run it twice with no source change
and the second run reports everything unchanged.
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


class TableSync(BaseModel):
    table: str
    source_object: str | None = None
    read: int = 0
    added: int = 0
    changed: int = 0
    unchanged: int = 0
    warnings: int = 0
    regressed: list[str] = Field(default_factory=list)
    vanished: list[str] = Field(default_factory=list)
    still_blocked: list[str] = Field(default_factory=list)
    still_needs_decision: list[str] = Field(default_factory=list)
    not_runnable: str | None = None

    @property
    def quiet(self) -> bool:
        """True when nothing changed and nothing needs attention."""
        return not (
            self.added or self.changed or self.regressed or self.vanished
        )


class Sync(BaseModel):
    run_id: str
    connection: str
    tenant_id: str
    started_at: str
    status: Literal["completed", "refused"]
    refused_because: str | None = None
    tables: list[TableSync] = Field(default_factory=list)

    def totals(self) -> dict[str, int]:
        c: Counter[str] = Counter()
        for t in self.tables:
            c.update(
                added=t.added,
                changed=t.changed,
                unchanged=t.unchanged,
                regressed=len(t.regressed),
                vanished=len(t.vanished),
            )
        return dict(c)

    def needs_attention(self) -> bool:
        return any(t.regressed or t.vanished for t in self.tables)


def run_sync(
    client: SalesforceClient,
    connection: str,
    db: TargetDB,
    limit: int = SCAN_LIMIT,
) -> Sync:
    """Bring the target in step with the source. Refuses without a current approval."""
    gate = approval.check(connection)
    base: dict[str, Any] = dict(
        run_id=uuid.uuid4().hex[:12],
        connection=connection,
        tenant_id=tenant_id(connection),
        started_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    if not gate["ok"]:
        return Sync(**base, status="refused", refused_because=gate["why"])

    sync = Sync(**base, status="completed")
    proposals = ProposalStore(connection).load()
    excluded = set(gate["approved"]["excluded"])
    tenant = sync.tenant_id

    for table, spec in TARGET_SCHEMA["tables"].items():
        fields = {f["name"]: {**f, "_table": table} for f in spec["fields"]}
        mapped = {
            name: (None if f"{table}.{name}" in excluded else proposals.get(f"{table}.{name}"))
            for name in fields
        }
        source_object, _ = _split((mapped["external_id"] or {}).get("source"))
        result = TableSync(table=table, source_object=source_object)
        sync.tables.append(result)
        if source_object is None:
            result.not_runnable = "No approved source for external_id; this table is not synced."
            continue
        try:
            describe = client.describe(source_object)
        except ObjectNotAccessible as exc:
            result.not_runnable = str(exc)
            continue

        in_target = db.external_ids(table, tenant)
        names = [f["name"] for f in describe["fields"] if f.get("type") not in UNSAMPLED_TYPES]
        seen: set[str] = set()
        for record_ in client.sample(source_object, names, limit):
            result.read += 1
            record_id = str(record_.get("Id"))
            seen.add(record_id)
            row, status, _issues = build_row(record_, fields, mapped, source_object)
            if status in ("blocking", "needs_decision"):
                if record_id in in_target:
                    # It loaded before; the source broke. Leave the good row untouched.
                    result.regressed.append(record_id)
                elif status == "blocking":
                    result.still_blocked.append(record_id)
                else:
                    result.still_needs_decision.append(record_id)
                continue
            if status == "warning":
                result.warnings += 1
            outcome = db.upsert(table, tenant, row)
            if outcome == "inserted":
                result.added += 1
            elif outcome == "updated":
                result.changed += 1
            else:
                result.unchanged += 1
        db.commit()
        # In the target but no longer seen in the source. Reported, never deleted.
        result.vanished = sorted(in_target - seen)

    save(sync)
    return sync


# --- storage ----------------------------------------------------------------------------


def _folder(connection: str) -> Path:
    return get_settings().state_dir / "syncs" / connection


def save(sync: Sync) -> Path:
    folder = _folder(sync.connection)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{sync.run_id}.json"
    path.write_text(sync.model_dump_json(indent=2) + "\n", encoding="utf-8")
    (folder / "latest").write_text(sync.run_id, encoding="utf-8")
    return path


def load(connection: str, run_id: str | None = None) -> Sync:
    folder = _folder(connection)
    if run_id is None:
        pointer = folder / "latest"
        if not pointer.is_file():
            raise ValueError(f"No sync has been run for {connection!r}.")
        run_id = pointer.read_text(encoding="utf-8").strip()
    if not run_id.isalnum():
        raise ValueError("Not a valid sync run id.")
    path = folder / f"{run_id}.json"
    if not path.is_file():
        raise ValueError(f"No sync {run_id!r} for {connection!r}.")
    return Sync.model_validate(json.loads(path.read_text(encoding="utf-8")))


def status_summary(sync: Sync) -> dict[str, Any]:
    """What the model may see: counts and the Ids that need a human, read-only."""
    return {
        "run_id": sync.run_id,
        "status": sync.status,
        "refused_because": sync.refused_because,
        "started_at": sync.started_at,
        "totals": sync.totals(),
        "needs_attention": sync.needs_attention(),
        "tables": [t.model_dump(exclude={"quiet"}) for t in sync.tables],
        "note": (
            "Sync inserts new records and updates changed ones. It never deletes and "
            "never overwrites a loaded record with a broken one. 'regressed' (was live, "
            "now fails validation) and 'vanished' (gone from the source) are reported for "
            "an administrator to decide; sync touches neither."
        ),
    }
