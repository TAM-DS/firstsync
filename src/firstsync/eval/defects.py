"""Score a dry-run against an org's planted defects.

The mapping score says whether Claude mapped the fields. This says whether the system
then caught the data problems we planted: a defect is `found` when every planted record
Id for it shows up in the dry-run's failure groups or duplicate groups. The engine is
deterministic code, so this is really a test of the whole pipeline: a wrong mapping
upstream makes a planted defect invisible downstream, and this score shows that.

`injection` is deliberately not here: injected text is a prompt-attack canary, scored
against the proposals, not a data defect the dry-run should flag.
"""

from __future__ import annotations

from typing import Any

from firstsync.dryrun import DryRun

# defect name in the answer key -> where its record Ids must appear in the dry-run
_WHERE: dict[str, tuple[str, ...]] = {
    "duplicate_contacts": ("duplicates:contacts",),
    "missing_email": ("group:contacts.email",),
    "missing_amount": ("group:deals.amount",),
    "short_phone": ("group:contacts.phone",),
}


def _ids(result: DryRun, where: str) -> set[str]:
    kind, _, name = where.partition(":")
    if kind == "duplicates":
        return {rid for d in result.duplicates if d.table == name for rid in d.record_ids}
    return {rid for g in result.groups if g.target == name for rid in g.record_ids}


def score_defects(key: dict[str, Any], result: DryRun) -> dict[str, Any] | None:
    """None when the org has no planted defects; otherwise found/missed per defect."""
    defects: dict[str, list[str]] = {
        name: ids for name, ids in (key.get("defects") or {}).items() if name in _WHERE
    }
    if not defects:
        return None
    out: dict[str, Any] = {}
    found_all = 0
    for name, planted in defects.items():
        flagged = set()
        for where in _WHERE[name]:
            flagged |= _ids(result, where)
        missed = sorted(set(planted) - flagged)
        out[name] = {"planted": len(planted), "found": len(planted) - len(missed)}
        if missed:
            out[name]["missed_ids"] = missed
        else:
            found_all += 1
    out["defects_found"] = f"{found_all}/{len(defects)}"
    return out
