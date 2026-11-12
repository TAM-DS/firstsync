"""Load a synthetic org into a live Salesforce Developer Edition org.

This is developer tooling for seeding test orgs you own. It is the only code in the
repository that writes to Salesforce, it is not reachable from the MCP server, and Claude
has no way to call it.

Records are inserted parents first. Fixture Ids are placeholders, so each reference field
is rewritten to the real Id Salesforce returned for its parent.
"""

from __future__ import annotations

from typing import Any

import httpx

BATCH = 200  # sObject Collections accepts up to 200 records per request
ORDER = ("Account", "Contact", "Opportunity", "Deal__c", "Task")


class LoadError(Exception):
    pass


def _payload(
    object_name: str, describe: dict[str, Any], record: dict[str, Any], id_map: dict[str, str]
) -> dict[str, Any]:
    references = {f["name"] for f in describe["fields"] if f["type"] == "reference"}
    body: dict[str, Any] = {"attributes": {"type": object_name}}
    for name, value in record.items():
        if name == "Id" or value is None:
            continue
        if name in references:
            if value not in id_map:
                raise LoadError(f"{object_name}.{name} points at {value}, which was not loaded.")
            value = id_map[value]
        body[name] = value
    return body


def load_fixture(
    fixture: dict[str, Any],
    instance_url: str,
    access_token: str,
    api_version: str = "v62.0",
    transport: httpx.BaseTransport | None = None,
) -> dict[str, int]:
    """Insert every record in the fixture. Returns the number created per object."""
    http = httpx.Client(
        base_url=f"{instance_url.rstrip('/')}/services/data/{api_version}",
        headers={"Authorization": f"Bearer {access_token}"},
        transport=transport,
        timeout=60.0,
    )
    id_map: dict[str, str] = {}
    created: dict[str, int] = {}
    objects = fixture["objects"]
    for object_name in [o for o in ORDER if o in objects]:
        describe, records = objects[object_name]["describe"], objects[object_name]["records"]
        created[object_name] = 0
        for start in range(0, len(records), BATCH):
            chunk = records[start : start + BATCH]
            body = {
                "allOrNone": True,
                "records": [_payload(object_name, describe, r, id_map) for r in chunk],
            }
            response = http.post("/composite/sobjects", json=body)
            if response.status_code >= 400:
                raise LoadError(f"{object_name}: HTTP {response.status_code} {response.text[:300]}")
            for source, result in zip(chunk, response.json(), strict=True):
                if not result.get("success"):
                    raise LoadError(f"{object_name} {source['Id']}: {result.get('errors')}")
                id_map[source["Id"]] = result["id"]
                created[object_name] += 1
    return created
