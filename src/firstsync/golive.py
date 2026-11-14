"""The go-live report.

One readable page an administrator gets at the end of onboarding and after every sync.
It pulls together what already happened — the approval, the last dry-run, the migration,
the latest sync — and says plainly where things stand: what is live, what is still open
and waiting on a decision, and what has changed or needs attention since go-live.

It computes nothing new and re-reads no source. It is a view over the state the other
engines already wrote, so it is cheap and always consistent with them.
"""

from __future__ import annotations

from typing import Any

from firstsync import approval, dryrun, migrate, sync


def _latest(loader: Any, connection: str) -> Any | None:
    try:
        return loader(connection)
    except ValueError:
        return None


def build(connection: str) -> dict[str, Any]:
    """Assemble the current state of one onboarding."""
    appr = approval.load(connection)
    dry = _latest(dryrun.load, connection)
    mig = _latest(migrate.load, connection)
    syn = _latest(sync.load, connection)

    report: dict[str, Any] = {"connection": connection}
    report["approved"] = (
        None
        if appr is None
        else {
            "by": appr["approved_by"],
            "at": appr["approved_at"],
            "fields": len(appr["proposal_sha256_16"]),
            "excluded": appr["excluded"],
            "open_questions": appr["open_questions"],
        }
    )
    report["migration"] = (
        None if mig is None else {"run_id": mig.run_id, "status": mig.status, **mig.totals()}
    )
    report["latest_sync"] = (
        None
        if syn is None
        else {
            "run_id": syn.run_id,
            "at": syn.started_at,
            "needs_attention": syn.needs_attention(),
            **syn.totals(),
        }
    )
    report["open_items"] = _open_items(appr, dry, syn)
    report["headline"] = _headline(report)
    return report


def _open_items(appr: Any, dry: Any, syn: Any) -> list[str]:
    items: list[str] = []
    if appr and appr["open_questions"]:
        items.append(
            f"{len(appr['open_questions'])} field(s) approved with an open question: "
            + ", ".join(appr["open_questions"])
        )
    if dry is not None:
        blocking = sum(t.blocking for t in dry.tables)
        decisions = sum(t.needs_decision for t in dry.tables)
        if blocking:
            items.append(f"{blocking} record(s) cannot load until the source is fixed")
        if decisions:
            items.append(f"{decisions} record(s) await an admin decision on an unmapped value")
    if syn is not None:
        for t in syn.tables:
            if t.regressed:
                items.append(
                    f"{t.table}: {len(t.regressed)} live record(s) regressed in the source"
                )
            if t.vanished:
                items.append(f"{t.table}: {len(t.vanished)} record(s) vanished from the source")
    return items


def _headline(report: dict[str, Any]) -> str:
    if report["approved"] is None:
        return "Not approved. Nothing has been migrated."
    if report["migration"] is None:
        return "Approved, but no migration has run yet."
    loaded = report["migration"].get("inserted", 0) + report["migration"].get("updated", 0)
    base = f"{loaded} record(s) live"
    if report["latest_sync"] and report["latest_sync"]["needs_attention"]:
        return base + "; the latest sync flagged items that need attention."
    if report["open_items"]:
        return base + f"; {len(report['open_items'])} open item(s)."
    return base + "; nothing outstanding."


def render(report: dict[str, Any]) -> str:
    """A plain-text version of the report for the CLI."""
    lines = [f"Onboarding: {report['connection']}", "=" * (12 + len(report["connection"])), ""]
    lines.append(report["headline"])
    lines.append("")
    a = report["approved"]
    if a:
        lines.append(f"Approved by {a['by']} at {a['at']} — {a['fields']} field(s).")
        if a["excluded"]:
            lines.append(f"  Excluded from the migration: {', '.join(a['excluded'])}")
    m = report["migration"]
    if m:
        lines.append(
            f"Migration {m['run_id']}: {m.get('inserted', 0)} inserted, "
            f"{m.get('updated', 0)} updated, {m.get('unchanged', 0)} unchanged, "
            f"{m.get('skipped', 0)} skipped."
        )
    s = report["latest_sync"]
    if s:
        lines.append(
            f"Latest sync {s['run_id']} at {s['at']}: {s.get('added', 0)} added, "
            f"{s.get('changed', 0)} changed, {s.get('regressed', 0)} regressed, "
            f"{s.get('vanished', 0)} vanished."
        )
    if report["open_items"]:
        lines.append("")
        lines.append("Open items:")
        lines.extend(f"  - {item}" for item in report["open_items"])
    return "\n".join(lines)
