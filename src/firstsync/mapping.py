"""Mapping proposals: what Claude submits, how they are checked, where they are kept.

A proposal says where one target field's value comes from and how it is transformed.
Proposals are validated against the live schema and the rule format before they are
stored. Storing a proposal changes no customer data; it waits for a human to approve.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from firstsync.config import get_settings
from firstsync.rules import asks_admin, concat_fields, validate_rule
from firstsync.salesforce import ObjectNotAccessible, SalesforceClient
from firstsync.target import TARGET_SCHEMA

CONFIDENCE = ("high", "medium", "low")
SOURCE = re.compile(r"^([A-Za-z][A-Za-z0-9_]{0,79})\.([A-Za-z][A-Za-z0-9_]{0,79})$")
ALLOWED_KEYS = {
    "target",
    "source",
    "confidence",
    "reason",
    "evidence",
    "rule",
    "question_for_admin",
}
MAX_TEXT = 600


def target_fields() -> dict[str, dict[str, Any]]:
    return {
        f"{table}.{field['name']}": field
        for table, spec in TARGET_SCHEMA["tables"].items()
        for field in spec["fields"]
    }


def _text(value: Any) -> bool:
    return isinstance(value, str) and 0 < len(value.strip()) <= MAX_TEXT


class SchemaCache:
    """Describe results for one validation pass, so each object is described once."""

    def __init__(self, client: SalesforceClient):
        self._client = client
        self._fields: dict[str, set[str] | None] = {}

    def fields(self, object_name: str) -> set[str] | None:
        if object_name not in self._fields:
            try:
                described = self._client.describe(object_name)
                self._fields[object_name] = {f["name"] for f in described["fields"]}
            except (ObjectNotAccessible, ValueError):
                self._fields[object_name] = None
        return self._fields[object_name]


def validate_mapping(mapping: Any, schema: SchemaCache) -> list[str]:
    """Return every problem with one proposal. An empty list means it can be stored."""
    if not isinstance(mapping, dict):
        return ["A mapping must be an object."]
    errors = [f"Unexpected key {k!r}." for k in mapping if k not in ALLOWED_KEYS]
    targets = target_fields()
    target = mapping.get("target")
    if target not in targets:
        return errors + [f"Unknown target field {target!r}."]
    field = targets[target]

    source = mapping.get("source")
    object_name = None
    if source is not None:
        match = SOURCE.match(source) if isinstance(source, str) else None
        if not match:
            errors.append("'source' must be 'Object.Field' or null.")
        else:
            object_name, field_name = match.groups()
            readable = schema.fields(object_name)
            if readable is None:
                errors.append(f"{object_name} does not exist or cannot be read.")
            elif field_name not in readable:
                errors.append(
                    f"{object_name}.{field_name} does not exist or is hidden from this user."
                )

    if mapping.get("confidence") not in CONFIDENCE:
        errors.append(f"'confidence' must be one of {list(CONFIDENCE)}.")
    if not _text(mapping.get("reason")):
        errors.append("'reason' is required: say what the evidence shows, in a sentence or two.")

    evidence = mapping.get("evidence", [])
    if not isinstance(evidence, list) or not all(_text(e) for e in evidence):
        errors.append("'evidence' must be a list of short strings.")
    elif source is not None and not evidence:
        errors.append("'evidence' is required when a source is given.")

    rule = mapping.get("rule", [])
    rule_errors = validate_rule(rule)
    errors += [f"rule: {e}" for e in rule_errors]
    if not rule_errors and object_name:
        readable = schema.fields(object_name) or set()
        for sibling in concat_fields(rule):
            if sibling not in readable:
                errors.append(f"rule: concat field {object_name}.{sibling} cannot be read.")

    question = mapping.get("question_for_admin")
    if question is not None and not _text(question):
        errors.append("'question_for_admin' must be a short question or null.")
    has_question = _text(question)
    has_default = not rule_errors and any(s.get("op") == "default" for s in rule)
    if mapping.get("confidence") == "low" and not has_question:
        errors.append("A low-confidence mapping needs a 'question_for_admin'.")
    if not rule_errors and asks_admin(rule) and not has_question:
        errors.append("A rule with unmapped='ask_admin' needs a 'question_for_admin'.")
    if source is None and field["required"] and not has_default and not has_question:
        errors.append(
            f"{target} is required. With no source it needs a default step or a "
            "'question_for_admin'."
        )
    return errors


def state_dir() -> Path:
    return get_settings().state_dir


class ProposalStore:
    """Accepted proposals for one connection, one per target field, kept as JSON."""

    def __init__(self, connection: str):
        self.path = state_dir() / "proposals" / f"{connection}.json"

    def load(self) -> dict[str, dict[str, Any]]:
        if not self.path.is_file():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, proposals: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(proposals, indent=2, sort_keys=True) + "\n", "utf-8")

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)


def coverage(proposals: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Which target fields have a proposal, and which required ones still need one."""
    targets = target_fields()
    missing_required = [t for t, f in targets.items() if f["required"] and t not in proposals]
    return {
        "proposed": len(proposals),
        "total_target_fields": len(targets),
        "required_without_proposal": missing_required,
        "open_questions": sorted(t for t, m in proposals.items() if m.get("question_for_admin")),
    }


def propose(
    client: SalesforceClient, store: ProposalStore, mappings: Any
) -> dict[str, Any]:
    """Validate each proposal; store the valid ones; report the rest with reasons."""
    if not isinstance(mappings, list) or not mappings:
        raise ValueError("'mappings' must be a non-empty list.")
    if len(mappings) > 60:
        raise ValueError("At most 60 mappings per call.")
    schema = SchemaCache(client)
    proposals = store.load()
    accepted, rejected = [], []
    for mapping in mappings:
        errors = validate_mapping(mapping, schema)
        target = mapping.get("target") if isinstance(mapping, dict) else None
        if errors or not isinstance(target, str):
            rejected.append({"target": target, "errors": errors})
            continue
        proposals[target] = {
            "target": target,
            "source": mapping.get("source"),
            "confidence": mapping["confidence"],
            "reason": mapping["reason"].strip(),
            "evidence": mapping.get("evidence", []),
            "rule": mapping.get("rule", []),
            "question_for_admin": mapping.get("question_for_admin"),
        }
        accepted.append(target)
    store.save(proposals)
    return {"accepted": accepted, "rejected": rejected, "coverage": coverage(proposals)}
