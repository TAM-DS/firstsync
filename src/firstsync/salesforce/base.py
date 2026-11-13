"""The read-only Salesforce interface the tools are written against.

There is no write method here on purpose. Nothing Claude can call is able to change the
customer's org.
"""

from __future__ import annotations

import re
from typing import Any, Protocol

# Salesforce API names: letters, digits and underscores, starting with a letter.
NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,79}$")

# Standard objects version 1 migrates. Custom objects are discovered, not listed.
STANDARD_OBJECTS = ("Account", "Contact", "Opportunity", "Task")


class SalesforceError(Exception):
    """A Salesforce request failed."""


class ObjectNotAccessible(SalesforceError):
    """The connected user cannot read this object, or it does not exist."""


def validate_name(name: str) -> str:
    """Reject anything that is not a plain API name.

    Object and field names come from the model, and the model reads untrusted customer
    data. They are checked before they are ever placed in a query.
    """
    if not isinstance(name, str) or not NAME.match(name):
        raise ValueError(f"Not a valid Salesforce API name: {name!r}")
    return name


class SalesforceClient(Protocol):
    def accessible_objects(self) -> list[dict[str, Any]]:
        """Objects in scope, each as {name, readable, custom, reason}."""

    def describe(self, object_name: str) -> dict[str, Any]:
        """The describe result for one object: {name, label, fields: [...]}."""

    def count(self, object_name: str) -> int:
        """Number of records in one object."""

    def sample(self, object_name: str, field_names: list[str], limit: int) -> list[dict[str, Any]]:
        """Up to `limit` raw records. Callers must mask these before use."""
