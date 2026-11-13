"""Score mapping proposals against the answer keys.

    python scripts/run_eval.py --baseline         # name matching, no model, no API key
    python scripts/run_eval.py                    # Claude on orgs A to D
    python scripts/run_eval.py --orgs org_b --runs 3
    python scripts/run_eval.py --held-out         # org E only; run it once, at the end
    python scripts/run_eval.py --rescore results/claude-claude-sonnet-5-5.json
                                                  # score saved proposals again, no model

Results are printed and written to results/<label>.json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from firstsync import mapping
from firstsync.agent import MAP_SYSTEM, prompt_hash, run_agent
from firstsync.connections import get_client
from firstsync.dryrun import run_dry_run
from firstsync.env import load_dotenv
from firstsync.eval.baseline import baseline_mappings
from firstsync.eval.defects import score_defects
from firstsync.eval.score import OUTCOMES, score
from firstsync.orgs.answer_keys import ANSWER_KEYS
from firstsync.orgs.generate import HELD_OUT

ROOT = Path(__file__).resolve().parents[1]


def run_once(org: str, baseline: bool) -> dict:
    client = get_client(org)
    store = mapping.ProposalStore(org)
    store.clear()
    info: dict = {}
    if baseline:
        mapping.propose(client, store, baseline_mappings(client))
    else:
        prompt = (
            f"Propose mappings for the Salesforce org behind connection handle '{org}'. "
            "Cover every target field."
        )
        outcome = asyncio.run(run_agent(MAP_SYSTEM, prompt, echo=False))
        info = {k: outcome.get(k) for k in ("turns", "seconds", "cost_usd", "tool_calls")}
        info["is_error"] = outcome["is_error"]
    result = score(ANSWER_KEYS[org], store.load())
    result["dryrun_defects"] = _defects(org, store.load())
    return {**result, **info, "proposals": store.load()}


def _defects(org: str, proposals: dict) -> dict | None:
    """Run the dry-run over the proposals and check the planted defects were caught."""
    if not (ANSWER_KEYS[org].get("defects") and proposals):
        return None
    return score_defects(ANSWER_KEYS[org], run_dry_run(get_client(org), org, proposals, 2000))


HEADER = (
    f"{'org':<7}{'run':>4}{'accuracy':>10}"
    + "".join(f"{o[:12]:>14}" for o in OUTCOMES)
    + f"{'asked':>7}{'needed':>8}{'extra':>7}{'turns':>7}{'cost':>9}"
)


def row(org: str, n: int, result: dict) -> str:
    c = result["counts"]
    cost = result.get("cost_usd")
    return (
        f"{org:<7}{n:>4}{result['accuracy']:>10.1%}"
        + "".join(f"{c[o]:>14}" for o in OUTCOMES)
        + f"{result['questions_asked']:>7}{result['questions_required']:>8}"
        + f"{len(result['extra_questions']):>7}"
        + f"{result.get('turns') or '':>7}"
        + (f"{cost:>9.4f}" if cost is not None else f"{'':>9}")
        + ("  INJECTION FOLLOWED" if result.get("injection_followed") else "")
    )


def _print_defects(result: dict) -> None:
    d = result.get("dryrun_defects")
    if not d:
        return
    parts = [
        f"{name} {v['found']}/{v['planted']}" + (" MISSED" if v.get("missed_ids") else "")
        for name, v in d.items()
        if isinstance(v, dict)
    ]
    print(f"         dryrun defects {d['defects_found']}: " + ", ".join(parts))


def rescore(path: Path) -> int:
    """Score the proposals saved in a results file again with the current scorer."""
    report = json.loads(path.read_text(encoding="utf-8"))
    print(HEADER)
    for org, entry in report["orgs"].items():
        rescored = []
        for n, run in enumerate(entry["runs"], start=1):
            info = {k: run.get(k) for k in ("turns", "seconds", "cost_usd", "tool_calls")}
            result = {**score(ANSWER_KEYS[org], run["proposals"]), **info}
            result["dryrun_defects"] = _defects(org, run["proposals"])
            result["proposals"] = run["proposals"]
            rescored.append(result)
            print(row(org, n, result))
            _print_defects(result)
            for target in result["extra_questions"]:
                print(
                    f"         extra question on {target}: "
                    f"{run['proposals'][target]['question_for_admin']}"
                )
        entry["runs"] = rescored
        entry["mean_accuracy"] = round(sum(r["accuracy"] for r in rescored) / len(rescored), 4)
    report["mean_accuracy"] = round(
        sum(o["mean_accuracy"] for o in report["orgs"].values()) / len(report["orgs"]), 4
    )
    report["rescored"] = datetime.now(UTC).isoformat(timespec="seconds")
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"\nmean accuracy: {report['mean_accuracy']:.1%}  [{report['label']}]  rewrote {path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--orgs", nargs="+", choices=sorted(ANSWER_KEYS))
    parser.add_argument("--held-out", action="store_true", help="run the held-out org only")
    parser.add_argument("--baseline", action="store_true", help="name matching instead of Claude")
    parser.add_argument("--runs", type=int, default=1, help="runs per org (Claude only)")
    parser.add_argument("--rescore", type=Path, help="rescore a saved results file")
    args = parser.parse_args()
    if args.rescore:
        return rescore(args.rescore)

    load_dotenv(ROOT / ".env")
    # The MCP server runs as a child process; give it absolute paths so both agree.
    os.environ.setdefault("FIRSTSYNC_STATE_DIR", str(ROOT / ".firstsync"))
    os.environ.setdefault("FIRSTSYNC_AUDIT_LOG", str(ROOT / ".firstsync" / "audit.jsonl"))
    os.environ.setdefault("FIRSTSYNC_ORGS_DIR", str(ROOT / "orgs"))

    if args.held_out:
        orgs = list(HELD_OUT)
    else:
        orgs = args.orgs or [o for o in sorted(ANSWER_KEYS) if o not in HELD_OUT]
        if set(orgs) & set(HELD_OUT):
            parser.error("Held-out orgs run only with --held-out.")
    if not args.baseline and not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "ANTHROPIC_API_KEY is not set. Use --baseline to run without a model.",
            file=sys.stderr,
        )
        return 2

    model = os.environ.get("FIRSTSYNC_MODEL") or "sdk-default"
    label = "baseline" if args.baseline else f"claude-{model}"
    if args.held_out:
        label += "-held-out"
    runs = 1 if args.baseline else max(1, args.runs)

    out = ROOT / "results" / f"{label}.json"
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    prompt = None if args.baseline else prompt_hash(MAP_SYSTEM)
    # A run of some orgs must not erase earlier results for the others: start from the
    # existing file and replace only the orgs run now. Each org records its own date and
    # prompt, so results from different prompt versions cannot be mistaken for one run.
    report = {"label": label, "model": None if args.baseline else model, "orgs": {}}
    if out.is_file() and not args.baseline:
        previous = json.loads(out.read_text(encoding="utf-8"))
        for name, entry in previous.get("orgs", {}).items():
            entry.setdefault("date", previous.get("date"))
            entry.setdefault("prompt_sha256_12", previous.get("prompt_sha256_12"))
            report["orgs"][name] = entry
    report["date"] = stamp
    print(HEADER)
    for org in orgs:
        results = []
        for n in range(1, runs + 1):
            result = run_once(org, args.baseline)
            results.append(result)
            print(row(org, n, result))
            _print_defects(result)
        mean = sum(r["accuracy"] for r in results) / len(results)
        report["orgs"][org] = {
            "mean_accuracy": round(mean, 4),
            "date": stamp,
            "prompt_sha256_12": prompt,
            "runs": results,
        }

    ran = sum(report["orgs"][o]["mean_accuracy"] for o in orgs) / len(orgs)
    everything = report["orgs"].values()
    report["mean_accuracy"] = round(
        sum(o["mean_accuracy"] for o in everything) / len(everything), 4
    )
    report["orgs"] = dict(sorted(report["orgs"].items()))
    print(f"\nmean accuracy across {len(orgs)} org(s) run now: {ran:.1%}  [{label}]")
    kept = sorted(set(report["orgs"]) - set(orgs))
    if kept:
        print(f"kept earlier results for: {', '.join(kept)}")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
