"""The firstsync command.

The subcommands an administrator or a developer actually needs:

    firstsync serve                 run the MCP server on stdio (what Claude talks to)
    firstsync dryrun ORG [--limit]  run stored proposals over real records, write nothing
    firstsync proposals ORG         list stored proposals and their approval state
    firstsync approve ORG           approve the proposals as they stand (human-only gate)
    firstsync migrate ORG --db PATH run the approved migration into the target database
    firstsync audit [--last N]      show the last audit-log entries

Approval and migration are deliberately CLI commands, not MCP tools: the model proposes;
a person authorizes.
"""

from __future__ import annotations

import argparse
import json
import sys

from firstsync import approval, audit, dryrun, migrate
from firstsync.connections import get_client
from firstsync.mapping import ProposalStore
from firstsync.target.db import TargetDB


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="firstsync", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("serve", help="Run the MCP server on stdio.")

    run = sub.add_parser("dryrun", help="Dry-run stored proposals for a connection.")
    run.add_argument("connection")
    run.add_argument("--limit", type=int, default=dryrun.PREVIEW_LIMIT)

    props = sub.add_parser("proposals", help="List stored proposals and approval state.")
    props.add_argument("connection")

    appr = sub.add_parser("approve", help="Approve the stored proposals as they stand.")
    appr.add_argument("connection")
    appr.add_argument("--except", dest="excluded", default="",
                      help="Comma-separated target fields to leave out of the approval.")
    appr.add_argument("--by", default=None, help="Name to record as the approver.")

    mig = sub.add_parser("migrate", help="Run the approved migration.")
    mig.add_argument("connection")
    mig.add_argument("--db", required=True, help="SQLite database path (created if absent).")
    mig.add_argument("--limit", type=int, default=dryrun.SCAN_LIMIT)

    log = sub.add_parser("audit", help="Show the last audit-log entries.")
    log.add_argument("--last", type=int, default=20)

    args = parser.parse_args(argv)

    if args.command == "serve":
        from firstsync.mcp_server import main as serve

        serve()
        return 0

    if args.command == "dryrun":
        try:
            result = dryrun.start(get_client(args.connection), args.connection, args.limit)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(json.dumps(dryrun.summary(result), indent=2))
        blocked = sum(t.blocking for t in result.tables)
        return 1 if blocked else 0

    if args.command == "proposals":
        stored = ProposalStore(args.connection).load()
        if not stored:
            print(f"No proposals stored for {args.connection!r}.", file=sys.stderr)
            return 2
        gate = approval.check(args.connection)
        state = "APPROVED" if gate["ok"] else gate["why"]
        print(f"{len(stored)} proposals for {args.connection}  [{state}]")
        for target, p in sorted(stored.items()):
            question = " ASKS" if p.get("question_for_admin") else ""
            print(f"  {target:<28} <- {p.get('source') or '(nothing)':<28} "
                  f"{p.get('confidence', '')}{question}")
        return 0

    if args.command == "approve":
        excluded = [t for t in args.excluded.split(",") if t]
        try:
            record = approval.approve(args.connection, excluded, args.by)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(f"Approved {len(record['proposal_sha256_16'])} proposals for "
              f"{args.connection} as {record['approved_by']}.")
        if record["open_questions"]:
            print("Open questions you are approving past (the dry-run flags these rows):")
            for target in record["open_questions"]:
                print(f"  {target}")
        return 0

    if args.command == "migrate":
        db = TargetDB(args.db)
        try:
            outcome = migrate.run_migration(
                get_client(args.connection), args.connection, db, args.limit
            )
        finally:
            db.close()
        print(json.dumps(migrate.status_summary(outcome), indent=2))
        return 0 if outcome.status == "completed" else 1

    path = audit.log_path()
    if not path.is_file():
        print("No audit log yet.", file=sys.stderr)
        return 2
    lines = path.read_text(encoding="utf-8").splitlines()[-args.last :]
    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
