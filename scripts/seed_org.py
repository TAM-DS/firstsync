"""Generate the synthetic test orgs, and optionally load one into a live Salesforce org.

    python scripts/seed_org.py                    # rewrite orgs/*/fixture.json and answer_key.json
    python scripts/seed_org.py --org org_b --live # also insert org_b's records into the org
                                                  # named by SF_INSTANCE_URL / SF_ACCESS_TOKEN

Loading org_b needs its custom fields and object deployed first; see orgs/org_b/salesforce.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from firstsync.orgs.answer_keys import ANSWER_KEYS
from firstsync.orgs.generate import BUILDERS
from firstsync.orgs.load import load_fixture

ROOT = Path(__file__).resolve().parents[1] / "orgs"


def write(org: str) -> dict:
    fixture = BUILDERS[org]()
    folder = ROOT / org
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "fixture.json").write_text(json.dumps(fixture, indent=1) + "\n", encoding="utf-8")
    (folder / "answer_key.json").write_text(
        json.dumps(ANSWER_KEYS[org], indent=2) + "\n", encoding="utf-8"
    )
    counts = {name: len(obj["records"]) for name, obj in fixture["objects"].items()}
    print(f"{org}: wrote fixture and answer key {counts}")
    return fixture


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--org", choices=sorted(BUILDERS), help="one org; default is all")
    parser.add_argument("--live", action="store_true", help="insert records into a live org")
    args = parser.parse_args()
    if args.live and not args.org:
        parser.error("--live needs --org, so records go to the org you meant.")

    for org in [args.org] if args.org else sorted(BUILDERS):
        fixture = write(org)
        if args.live:
            try:
                url, token = os.environ["SF_INSTANCE_URL"], os.environ["SF_ACCESS_TOKEN"]
            except KeyError as missing:
                print(f"Missing environment variable {missing}.", file=sys.stderr)
                return 2
            created = load_fixture(fixture, url, token, os.environ.get("SF_API_VERSION", "v62.0"))
            print(f"{org}: created in {url}: {created}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
