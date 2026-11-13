"""The target schema: a small reference customer-success app.

Four tables. `external_id` on every table holds the Salesforce record Id so a migration
can be re-run without creating duplicates. `natural_key` names the fields that identify
the same real-world thing, which the dry-run uses to warn about likely duplicates.
schema.sql is the same schema as Postgres DDL.
"""

from __future__ import annotations

from typing import Any


def _field(
    name: str,
    type_: str,
    *,
    required: bool = False,
    values: list[str] | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    field: dict[str, Any] = {"name": name, "type": type_, "required": required}
    if values:
        field["values"] = values
    if note:
        field["note"] = note
    return field


TARGET_SCHEMA: dict[str, Any] = {
    "name": "reference-customer-success-app",
    "tables": {
        "accounts": {
            "description": "A customer company.",
            "natural_key": ["name"],
            "fields": [
                _field("external_id", "text", required=True, note="Source record Id."),
                _field("name", "text", required=True),
                _field("industry", "text"),
                _field("tier", "enum", values=["free", "standard", "enterprise"]),
                _field("website", "text"),
                _field("customer_since", "date", note="ISO 8601 date."),
                _field("owner_email", "email"),
            ],
        },
        "contacts": {
            "description": "A person at a customer company.",
            "natural_key": ["email"],
            "fields": [
                _field("external_id", "text", required=True, note="Source record Id."),
                _field("account_external_id", "text", required=True),
                _field("first_name", "text"),
                _field("last_name", "text", required=True),
                _field("email", "email", required=True),
                _field("phone", "text", note="E.164 format, for example +15125550100."),
                _field(
                    "role",
                    "enum",
                    values=["decision_maker", "champion", "billing", "technical", "other"],
                    note="The person's role in the buying relationship, not their job title.",
                ),
            ],
        },
        "deals": {
            "description": "A sales opportunity with a customer company.",
            "fields": [
                _field("external_id", "text", required=True, note="Source record Id."),
                _field("account_external_id", "text", required=True),
                _field("name", "text", required=True),
                _field("amount", "numeric", required=True),
                _field("currency", "text", required=True, note="ISO 4217 code. Default USD."),
                _field(
                    "stage",
                    "enum",
                    required=True,
                    values=[
                        "lead",
                        "qualified",
                        "proposal",
                        "negotiation",
                        "closed_won",
                        "closed_lost",
                    ],
                ),
                _field("close_date", "date", note="ISO 8601 date."),
                _field("owner_email", "email"),
            ],
        },
        "activities": {
            "description": "A logged interaction with an account or a deal.",
            "fields": [
                _field("external_id", "text", required=True, note="Source record Id."),
                _field("related_type", "enum", required=True, values=["account", "deal"]),
                _field("related_external_id", "text", required=True),
                _field("kind", "enum", required=True, values=["call", "email", "meeting", "task"]),
                _field("subject", "text", required=True),
                _field("occurred_at", "timestamp", required=True, note="ISO 8601, UTC."),
                _field("notes", "text"),
            ],
        },
    },
}


def required_fields() -> list[str]:
    """Every required target field as 'table.field'."""
    return [
        f"{table}.{field['name']}"
        for table, spec in TARGET_SCHEMA["tables"].items()
        for field in spec["fields"]
        if field["required"]
    ]
