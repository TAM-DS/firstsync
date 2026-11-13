"""A no-model baseline mapper: match fields by name.

This is the floor Claude has to beat. It is what a simple integration tool does: line up
`first_name` with `FirstName` and stop. It cannot see that `Field_7__c` holds an industry,
and it never asks a question.
"""

from __future__ import annotations

import re
from typing import Any

from firstsync.mapping import target_fields
from firstsync.salesforce import SalesforceClient

TABLE_OBJECT = {
    "accounts": "Account",
    "contacts": "Contact",
    "deals": "Opportunity",
    "activities": "Task",
}
SPECIAL = {"external_id": "id", "account_external_id": "accountid"}


def _norm(name: str) -> str:
    return re.sub(r"(__c$)|_", "", name).lower()


def baseline_mappings(client: SalesforceClient) -> list[dict[str, Any]]:
    readable = {o["name"] for o in client.accessible_objects() if o["readable"]}
    fields_by_object = {
        name: {_norm(f["name"]): f["name"] for f in client.describe(name)["fields"]}
        for name in readable
    }
    mappings = []
    for target in target_fields():
        table, field = target.split(".")
        object_name = TABLE_OBJECT[table]
        wanted = SPECIAL.get(field, _norm(field))
        match = fields_by_object.get(object_name, {}).get(wanted)
        if match is None:
            continue
        mappings.append(
            {
                "target": target,
                "source": f"{object_name}.{match}",
                "confidence": "medium",
                "reason": "The source field name matches the target field name.",
                "evidence": [f"describe:{object_name}.{match}"],
                "rule": [{"op": "copy"}],
                "question_for_admin": None,
            }
        )
    return mappings
