"""Claude describes an org using only the FirstSync tools.

    pip install -e ".[agent]"
    export ANTHROPIC_API_KEY=...        # or put it in a .env file
    python scripts/describe_org.py org_b
"""

from __future__ import annotations

import asyncio
import sys

from firstsync.agent import DESCRIBE_SYSTEM, run_agent
from firstsync.env import load_dotenv


def main() -> int:
    load_dotenv()
    connection = sys.argv[1] if len(sys.argv) > 1 else "org_b"
    prompt = f"Inspect the Salesforce org behind connection handle '{connection}' and report."
    outcome = asyncio.run(run_agent(DESCRIBE_SYSTEM, prompt, max_turns=30))
    cost = outcome.get("cost_usd")
    print(
        f"\n[{outcome.get('turns')} turns, {outcome.get('seconds')}s"
        + (f", ${cost:.4f}" if cost is not None else "")
        + f", model {outcome['model']}]",
        file=sys.stderr,
    )
    return 1 if outcome["is_error"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
