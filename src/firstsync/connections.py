"""Connection handles.

Tools are given a handle such as "org_b" or "live", never a credential. This module turns
a handle into a client. In development a handle is either a fixture org in the orgs/
folder or "live", which reads the environment. The portal's token vault replaces this
in week 4 without changing any tool signature.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from firstsync.salesforce import FixtureSalesforceClient, RestSalesforceClient, SalesforceClient

HANDLE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")


class UnknownConnection(ValueError):
    pass


def orgs_dir() -> Path:
    override = os.environ.get("FIRSTSYNC_ORGS_DIR")
    return Path(override) if override else Path(__file__).resolve().parents[2] / "orgs"


def available_fixtures() -> list[str]:
    root = orgs_dir()
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if (p / "fixture.json").is_file())


def get_client(handle: str) -> SalesforceClient:
    if not isinstance(handle, str) or not HANDLE.match(handle):
        raise UnknownConnection(f"Not a valid connection handle: {handle!r}")
    if handle == "live":
        return RestSalesforceClient.from_env()
    fixture = orgs_dir() / handle / "fixture.json"
    if fixture.is_file():
        return FixtureSalesforceClient.from_file(fixture)
    raise UnknownConnection(
        f"No connection named {handle!r}. Available: {', '.join(available_fixtures() + ['live'])}"
    )
