"""Score mapping proposals against the answer keys.

    python scripts/run_eval.py --baseline         # name matching, no model, no API key
    python scripts/run_eval.py                    # Claude on orgs A to D
    python scripts/run_eval.py --orgs org_b --runs 3
    python scripts/run_eval.py --held-out         # org E only; run it once, at the end

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
from firstsync.env import load_dotenv
from firstsync.eval.baseline import baseline_mappings
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
    return {**result, **info, "proposals": store.load()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--orgs", nargs="+", choices=sorted(ANSWER_KEYS))
    parser.add_argument("--held-out", action="store_true", help="run the held-out org only")
    parser.add_argument("--baseline", action="store_true", help="name matching instead of Claude")
    parser.add_argument("--runs", type=int, default=1, help="runs per org (Claude only)")
    args = parser.parse_args()

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

    report = {
        "label": label,
        "date": datetime.now(UTC).isoformat(timespec="seconds"),
        "model": None if args.baseline else model,
        "prompt_sha256_12": None if args.baseline else prompt_hash(MAP_SYSTEM),
        "runs_per_org": runs,
        "orgs": {},
    }
    header = f"{'org':<7}{'run':>4}{'accuracy':>10}" + "".join(f"{o[:12]:>14}" for o in OUTCOMES)
    print(header + f"{'turns':>7}{'cost':>9}")
    for org in orgs:
        results = []
        for n in range(1, runs + 1):
            result = run_once(org, args.baseline)
            results.append(result)
            c = result["counts"]
            cost = result.get("cost_usd")
            print(
                f"{org:<7}{n:>4}{result['accuracy']:>10.1%}"
                + "".join(f"{c[o]:>14}" for o in OUTCOMES)
                + f"{result.get('turns') or '':>7}"
                + (f"{cost:>9.4f}" if cost is not None else f"{'':>9}")
                + ("  INJECTION FOLLOWED" if result.get("injection_followed") else "")
            )
        mean = sum(r["accuracy"] for r in results) / len(results)
        report["orgs"][org] = {"mean_accuracy": round(mean, 4), "runs": results}

    overall = sum(o["mean_accuracy"] for o in report["orgs"].values()) / len(report["orgs"])
    report["mean_accuracy"] = round(overall, 4)
    print(f"\nmean accuracy across {len(orgs)} org(s): {overall:.1%}  [{label}]")
    out = ROOT / "results" / f"{label}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
