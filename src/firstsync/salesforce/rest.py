"""A read-only Salesforce REST client.

Only GET requests are made. For development the instance URL and access token come from
the environment; the portal's OAuth flow replaces that in week 4.
"""

from __future__ import annotations

import os
import random
import time
from typing import Any

import httpx

from firstsync.salesforce.base import (
    STANDARD_OBJECTS,
    ObjectNotAccessible,
    SalesforceError,
    validate_name,
)

# Compound fields cannot be selected alongside their parts in every context; skip them.
UNSAMPLED_TYPES = {"address", "location"}

# Worth retrying: rate limits and transient server errors. 400/401/403/404 are not.
RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 4
BASE_DELAY = 0.5  # seconds; grows 0.5, 1, 2 with jitter


def _sleep_before(attempt: int, sleep: Any = time.sleep) -> None:
    """Exponential backoff with full jitter, so retries from many workers spread out."""
    sleep(random.uniform(0, BASE_DELAY * (2**attempt)))


class RestSalesforceClient:
    def __init__(
        self,
        instance_url: str,
        access_token: str,
        api_version: str = "v62.0",
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
    ):
        self._http = httpx.Client(
            base_url=f"{instance_url.rstrip('/')}/services/data/{api_version}",
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            transport=transport,
            timeout=timeout,
        )

    @classmethod
    def from_env(cls) -> RestSalesforceClient:
        try:
            instance_url = os.environ["SF_INSTANCE_URL"]
            access_token = os.environ["SF_ACCESS_TOKEN"]
        except KeyError as missing:
            raise SalesforceError(f"Missing environment variable {missing}.") from None
        return cls(instance_url, access_token, os.environ.get("SF_API_VERSION", "v62.0"))

    def _get(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        """GET with retries. Reads are idempotent, so retrying a timeout is always safe."""
        last_error: str = ""
        for attempt in range(MAX_ATTEMPTS):
            if attempt:
                _sleep_before(attempt - 1)
            try:
                response = self._http.get(path, params=params)
            except httpx.HTTPError as exc:
                last_error = f"Salesforce request failed: {exc}"
                continue
            if response.status_code in RETRY_STATUSES:
                last_error = f"Salesforce returned {response.status_code} for {path}."
                continue
            if response.status_code in (403, 404):
                raise ObjectNotAccessible(
                    f"Salesforce returned {response.status_code} for {path}."
                )
            if response.status_code >= 400:
                raise SalesforceError(
                    f"Salesforce returned {response.status_code} for {path}: "
                    f"{response.text[:300]}"
                )
            return response.json()
        raise SalesforceError(f"{last_error} Gave up after {MAX_ATTEMPTS} attempts.")

    def accessible_objects(self) -> list[dict[str, Any]]:
        listed = {o["name"]: o for o in self._get("/sobjects")["sobjects"]}
        result = []
        for name in STANDARD_OBJECTS:
            found = listed.get(name)
            readable = bool(found and found.get("queryable"))
            result.append(
                {
                    "name": name,
                    "readable": readable,
                    "custom": False,
                    "reason": None if readable else "The connected user has no Read permission.",
                }
            )
        for name, found in sorted(listed.items()):
            if found.get("custom") and name.endswith("__c") and found.get("queryable"):
                result.append({"name": name, "readable": True, "custom": True, "reason": None})
        return result

    def describe(self, object_name: str) -> dict[str, Any]:
        return self._get(f"/sobjects/{validate_name(object_name)}/describe")

    def count(self, object_name: str) -> int:
        soql = f"SELECT COUNT() FROM {validate_name(object_name)}"
        return int(self._get("/query", {"q": soql})["totalSize"])

    def sample(self, object_name: str, field_names: list[str], limit: int) -> list[dict[str, Any]]:
        fields = ", ".join(validate_name(f) for f in field_names)
        if not fields:
            return []
        soql = f"SELECT {fields} FROM {validate_name(object_name)} LIMIT {int(limit)}"
        records = self._get("/query", {"q": soql})["records"]
        return [{k: v for k, v in record.items() if k != "attributes"} for record in records]
