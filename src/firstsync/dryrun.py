"""The dry-run engine.

Takes the stored mapping proposals for a connection and runs them over real records,
without writing anything anywhere. For every record it builds the row that would be
loaded into the target, checks each value against the target's rules, and records what
went wrong. Failures are grouped by field and reason so that fifty records failing for
one cause read as one finding, not fifty.

The engine is deterministic: the same proposals over the same records give the same
result. What it returns is safe to show the model. Values are masked exactly as samples
are, and failure reasons never contain the value that failed. Record Ids are kept,
because they are how an administrator finds the record.
"""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from firstsync.config import get_settings
from firstsync.mapping import SOURCE, ProposalStore
from firstsync.masking import display, field_treatments
from firstsync.rules import RuleFailure, UnmappedValue, apply_rule, check_target_value
from firstsync.salesforce import ObjectNotAccessible, SalesforceClient
from firstsync.salesforce.rest import UNSAMPLED_TYPES
from firstsync.target import TARGET_SCHEMA

PREVIEW_LIMIT = 50  # what an administrator sees first
SCAN_LIMIT = 2000  # the most one dry-run will read per object
MAX_IDS_PER_GROUP = 25

Severity = Literal["blocking", "needs_decision", "warning"]
# A record's status is its worst issue, in this order.
RANK: dict[str, int] = {"clean": 0, "warning": 1, "needs_decision": 2, "blocking": 3}


class FailureGroup(BaseModel):
    """Every record that failed on one target field for one reason."""

    target: str
    reason: str
    severity: Severity
    count: int
    record_ids: list[str] = Field(description="Source record Ids, at most 25.")
    example_input: Any = Field(description="One failing input, masked.")


class DuplicateGroup(BaseModel):
    """Records that would load as the same real-world thing."""

    table: str
    key: list[str]
    record_ids: list[str]


class TableResult(BaseModel):
    table: str
    source_object: str | None
    records: int = 0
    clean: int = 0
    warning: int = 0
    needs_decision: int = 0
    blocking: int = 0
    dead_lettered: int = Field(
        default=0, description="Records that crashed the engine; filed, not fatal."
    )
    not_runnable: str | None = None


class DryRun(BaseModel):
    run_id: str
    connection: str
    started_at: str
    limit: int
    wrote_anything: Literal[False] = False
    tables: list[TableResult]
    groups: list[FailureGroup]
    duplicates: list[DuplicateGroup]
    preview: dict[str, list[dict[str, Any]]]


def _severity(field: dict[str, Any], failure: Exception) -> Severity:
    if isinstance(failure, UnmappedValue):
        return "needs_decision"
    # A bad value in a required field stops the record. In an optional field the value
    # would be dropped and the record would still load.
    return "blocking" if field["required"] else "warning"


def _split(source: str | None) -> tuple[str | None, str | None]:
    if source is None:
        return None, None
    match = SOURCE.match(source)
    return (match.group(1), match.group(2)) if match else (None, None)


def run_dry_run(
    client: SalesforceClient,
    connection: str,
    proposals: dict[str, dict[str, Any]],
    limit: int = PREVIEW_LIMIT,
) -> DryRun:
    limit = max(1, min(int(limit), SCAN_LIMIT))
    tables: list[TableResult] = []
    groups: dict[tuple[str, str], FailureGroup] = {}
    duplicates: list[DuplicateGroup] = []
    preview: dict[str, list[dict[str, Any]]] = {}

    for table, spec in TARGET_SCHEMA["tables"].items():
        fields = {f["name"]: f for f in spec["fields"]}
        mapped = {name: proposals.get(f"{table}.{name}") for name in fields}
        source_object, _ = _split((mapped["external_id"] or {}).get("source"))
        result = TableResult(table=table, source_object=source_object)
        tables.append(result)
        if source_object is None:
            result.not_runnable = "No source is proposed for external_id, so no record can be read."
            continue
        try:
            describe = client.describe(source_object)
        except ObjectNotAccessible as exc:
            result.not_runnable = str(exc)
            continue
        names = [f["name"] for f in describe["fields"] if f.get("type") not in UNSAMPLED_TYPES]
        records = client.sample(source_object, names, limit)
        treatments = field_treatments(describe, records)
        rows: list[tuple[str, dict[str, Any]]] = []
        shown: list[dict[str, Any]] = []

        for record in records:
            record_id = str(record.get("Id"))
            try:
                _one_record(
                    record, record_id, fields, mapped, source_object, treatments,
                    table, groups, result, rows, shown,
                )
            except Exception as exc:  # noqa: BLE001 - one bad record must not kill the scan
                result.dead_lettered += 1
                _dead_letter(connection, table, record_id, exc)

        preview[table] = shown
        duplicates += _duplicates(table, spec.get("natural_key"), rows)

    ordered = sorted(groups.values(), key=lambda g: (-RANK[g.severity], -g.count, g.target))
    return DryRun(
        run_id=uuid.uuid4().hex[:12],
        connection=connection,
        started_at=datetime.now(UTC).isoformat(timespec="seconds"),
        limit=limit,
        tables=tables,
        groups=ordered,
        duplicates=duplicates,
        preview=preview,
    )


def _one_record(
    record: dict[str, Any],
    record_id: str,
    fields: dict[str, dict[str, Any]],
    mapped: dict[str, dict[str, Any] | None],
    source_object: str,
    treatments: dict[str, str],
    table: str,
    groups: dict[tuple[str, str], FailureGroup],
    result: TableResult,
    rows: list[tuple[str, dict[str, Any]]],
    shown: list[dict[str, Any]],
) -> None:
    row: dict[str, Any] = {}
    visible_row: dict[str, Any] = {}
    status = "clean"
    for name, field in fields.items():
        proposal = mapped[name]
        target = f"{table}.{name}"
        if proposal is None:
            value, failure = None, None
            reason = check_target_value(field, None)
            treatment = "pass"
        else:
            obj, src = _split(proposal.get("source"))
            treatment = treatments.get(src or "", "pass") if obj else "pass"
            raw = record.get(src) if obj == source_object and src else None
            failure, reason, value = None, None, None
            if obj is not None and obj != source_object:
                reason = f"source is on {obj}, but this table is read from {source_object}"
            else:
                try:
                    value = apply_rule(proposal.get("rule", []), raw, record)
                    reason = check_target_value(field, value)
                except RuleFailure as exc:
                    failure, reason = exc, str(exc)
        if reason is None:
            row[name] = value
            hidden = treatment in ("shape", "summary") or _uses_concat(proposal)
            visible_row[name] = display("shape", value) if hidden else value
            continue
        severity = _severity(field, failure or RuleFailure(reason))
        if RANK[severity] > RANK[status]:
            status = severity
        source_field = _split((proposal or {}).get("source"))[1]
        shown_input = display(treatment, record.get(source_field or ""))
        group = groups.setdefault(
            (target, reason),
            FailureGroup(
                target=target,
                reason=reason,
                severity=severity,
                count=0,
                record_ids=[],
                example_input=shown_input,
            ),
        )
        group.count += 1
        if len(group.record_ids) < MAX_IDS_PER_GROUP:
            group.record_ids.append(record_id)
    result.records += 1
    setattr(result, status, getattr(result, status) + 1)
    rows.append((record_id, row))
    if len(shown) < 5:
        shown.append({"source_id": record_id, "status": status, "row": visible_row})


def _dead_letter(connection: str, table: str, record_id: str, exc: Exception) -> None:
    """File a record the engine could not process, so it is investigated, not lost."""
    folder = _folder(connection)
    folder.mkdir(parents=True, exist_ok=True)
    entry = {
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
        "run_id": get_settings().run_id,
        "table": table,
        "record_id": record_id,
        "error": f"{type(exc).__name__}: {exc}",
    }
    with (folder / "deadletter.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")


def _uses_concat(proposal: dict[str, Any] | None) -> bool:
    return any(step.get("op") == "concat" for step in (proposal or {}).get("rule", []))


def _duplicates(
    table: str, key: list[str] | None, rows: list[tuple[str, dict[str, Any]]]
) -> list[DuplicateGroup]:
    if not key:
        return []
    seen: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for record_id, row in rows:
        values = [row.get(k) for k in key]
        if all(isinstance(v, str) and v.strip() for v in values):
            seen[tuple(str(v).strip().lower() for v in values)].append(record_id)
    return [
        DuplicateGroup(table=table, key=key, record_ids=ids)
        for ids in seen.values()
        if len(ids) > 1
    ]


# --- storage ----------------------------------------------------------------------------


def _folder(connection: str) -> Path:
    return get_settings().state_dir / "dryruns" / connection


def save(result: DryRun) -> Path:
    folder = _folder(result.connection)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{result.run_id}.json"
    path.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    (folder / "latest").write_text(result.run_id, encoding="utf-8")
    return path


def load(connection: str, run_id: str | None = None) -> DryRun:
    folder = _folder(connection)
    if run_id is None:
        pointer = folder / "latest"
        if not pointer.is_file():
            raise ValueError(f"No dry-run has been run for {connection!r}.")
        run_id = pointer.read_text(encoding="utf-8").strip()
    if not run_id.isalnum():
        raise ValueError("Not a valid dry-run id.")
    path = folder / f"{run_id}.json"
    if not path.is_file():
        raise ValueError(f"No dry-run {run_id!r} for {connection!r}.")
    return DryRun.model_validate(json.loads(path.read_text(encoding="utf-8")))


def start(client: SalesforceClient, connection: str, limit: int = PREVIEW_LIMIT) -> DryRun:
    """Run the stored proposals for a connection, save the result, and return it."""
    proposals = ProposalStore(connection).load()
    if not proposals:
        raise ValueError(f"No mapping proposals are stored for {connection!r}. Propose first.")
    result = run_dry_run(client, connection, proposals, limit)
    save(result)
    return result


def summary(result: DryRun, max_groups: int = 20) -> dict[str, Any]:
    """The part of a dry-run worth returning from a tool call."""
    return {
        "run_id": result.run_id,
        "limit": result.limit,
        "wrote_anything": False,
        "tables": [t.model_dump() for t in result.tables],
        "failure_groups": [g.model_dump() for g in result.groups[:max_groups]],
        "failure_groups_total": len(result.groups),
        "duplicates": [d.model_dump() for d in result.duplicates[:max_groups]],
        "note": (
            "Nothing was written. Rules ran on real values; what is shown is masked. "
            "blocking: the record cannot load. needs_decision: the administrator must "
            "decide. warning: the value would be dropped and the record would still load."
        ),
    }
