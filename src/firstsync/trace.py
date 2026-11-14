"""A reviewer's view over the audit log.

Every tool call has been recorded since week 1 — what was asked, whether it succeeded, a
hash of what came back, and the run ID that ties one onboarding session together. This
module reads that log back and summarizes it, so an operator can answer the question an
FDE is always asked: *what did the agent actually do, and did any of it fail?*

It reads only. It never writes, and it is not an MCP tool — the agent does not get to
narrate its own record; a person reads it.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from firstsync import audit


class RunTrace(BaseModel):
    run_id: str
    connections: list[str] = Field(default_factory=list)
    started_at: str | None = None
    ended_at: str | None = None
    calls: int = 0
    failures: int = 0
    tools: dict[str, int] = Field(default_factory=dict)
    stages: list[str] = Field(default_factory=list)
    errors: list[dict[str, str]] = Field(default_factory=list)


def read_entries(path: Path | None = None) -> list[dict[str, Any]]:
    """Every audit entry, oldest first. Malformed lines are skipped, not fatal."""
    path = path or audit.log_path()
    if not path.is_file():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def _summarize(run_id: str, entries: list[dict[str, Any]]) -> RunTrace:
    tools: Counter[str] = Counter()
    stages: list[str] = []
    connections: list[str] = []
    errors: list[dict[str, str]] = []
    failures = 0
    for e in entries:
        tools[e.get("tool", "?")] += 1
        stage = e.get("stage")
        if stage and stage not in stages:
            stages.append(stage)
        conn = e.get("connection")
        if conn and conn not in connections:
            connections.append(conn)
        if not e.get("ok", True):
            failures += 1
            errors.append({"tool": e.get("tool", "?"), "error": e.get("error", "")})
    stamps = [e["ts"] for e in entries if e.get("ts")]
    return RunTrace(
        run_id=run_id,
        connections=connections,
        started_at=min(stamps) if stamps else None,
        ended_at=max(stamps) if stamps else None,
        calls=len(entries),
        failures=failures,
        tools=dict(sorted(tools.items())),
        stages=stages,
        errors=errors,
    )


def runs(path: Path | None = None, connection: str | None = None) -> list[RunTrace]:
    """One trace per run_id, most recent first (by first-seen timestamp)."""
    entries = read_entries(path)
    if connection is not None:
        entries = [e for e in entries if e.get("connection") == connection]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for e in entries:
        grouped.setdefault(e.get("run_id", "?"), []).append(e)
    traces = [_summarize(rid, es) for rid, es in grouped.items()]
    return sorted(traces, key=lambda t: t.started_at or "", reverse=True)


def one(run_id: str, path: Path | None = None) -> RunTrace:
    entries = [e for e in read_entries(path) if e.get("run_id") == run_id]
    if not entries:
        raise ValueError(f"No audit entries for run {run_id!r}.")
    return _summarize(run_id, entries)


def render_list(traces: list[RunTrace]) -> str:
    if not traces:
        return "No audit entries yet."
    lines = [f"{'run':<14}{'when':<22}{'calls':>6}{'fail':>5}  tools"]
    for t in traces:
        busiest = sorted(t.tools.items(), key=lambda x: -x[1])[:3]
        top = ", ".join(f"{name}×{n}" for name, n in busiest)
        lines.append(
            f"{t.run_id:<14}{(t.started_at or ''):<22}{t.calls:>6}{t.failures:>5}  {top}"
        )
    return "\n".join(lines)


def render_run(t: RunTrace) -> str:
    lines = [
        f"Run {t.run_id}",
        f"  connection(s): {', '.join(t.connections) or '(none)'}",
        f"  window:        {t.started_at} -> {t.ended_at}",
        f"  stages:        {' -> '.join(t.stages) or '(none)'}",
        f"  calls:         {t.calls} ({t.failures} failed)",
        "  tools:",
    ]
    lines += [f"    {name:<22}{n}" for name, n in t.tools.items()]
    if t.errors:
        lines.append("  failures:")
        lines += [f"    {e['tool']}: {e['error']}" for e in t.errors]
    return "\n".join(lines)
