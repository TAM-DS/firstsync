"""A Salesforce client backed by a JSON fixture.

Used for tests, for the evaluation, and for developing without a live org. It behaves
the way Salesforce does when access is missing: a field the user cannot read is absent
from the describe result and from records, and an object the user cannot read fails.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from firstsync.salesforce.base import ObjectNotAccessible, validate_name


class FixtureSalesforceClient:
    def __init__(self, fixture: dict[str, Any]):
        self._objects: dict[str, Any] = fixture["objects"]
        self._denied_objects: set[str] = set(fixture.get("denied_objects", []))
        self._denied_fields: dict[str, set[str]] = {
            name: set(fields) for name, fields in fixture.get("denied_fields", {}).items()
        }

    @classmethod
    def from_file(cls, path: Path) -> FixtureSalesforceClient:
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def _object(self, object_name: str) -> dict[str, Any]:
        validate_name(object_name)
        if object_name in self._denied_objects or object_name not in self._objects:
            raise ObjectNotAccessible(
                f"{object_name} does not exist or the connected user cannot read it."
            )
        return self._objects[object_name]

    def accessible_objects(self) -> list[dict[str, Any]]:
        result = []
        for name, obj in self._objects.items():
            denied = name in self._denied_objects
            result.append(
                {
                    "name": name,
                    "readable": not denied,
                    "custom": obj["describe"].get("custom", name.endswith("__c")),
                    "reason": "The connected user has no Read permission." if denied else None,
                }
            )
        return result

    def describe(self, object_name: str) -> dict[str, Any]:
        describe = copy.deepcopy(self._object(object_name)["describe"])
        hidden = self._denied_fields.get(object_name, set())
        describe["fields"] = [f for f in describe["fields"] if f["name"] not in hidden]
        return describe

    def count(self, object_name: str) -> int:
        return len(self._object(object_name)["records"])

    def sample(self, object_name: str, field_names: list[str], limit: int) -> list[dict[str, Any]]:
        visible = {f["name"] for f in self.describe(object_name)["fields"]}
        wanted = [validate_name(f) for f in field_names if f in visible]
        records = self._object(object_name)["records"][: max(0, limit)]
        return [{name: record.get(name) for name in wanted} for record in records]
