"""The firstsync command.

Three subcommands an administrator or a developer actually needs:

    firstsync serve                 run the MCP server on stdio (what Claude talks to)
    firstsync dryrun ORG [--limit]  run stored proposals over real records, write nothing
    firstsync audit [--last N]      show the last audit-log entries

Everything else happens through Claude; the CLI is the deterministic side.
"""

from __future__ import annotations

import argparse
import json
import sys

from firstsync import audit, dryrun
from firstsync.connections import get_client


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="firstsync", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("serve", help="Run the MCP server on stdio.")

    run = sub.add_parser("dryrun", help="Dry-run stored proposals for a connection.")
    run.add_argument("connection")
    run.add_argument("--limit", type=int, default=dryrun.PREVIEW_LIMIT)

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
