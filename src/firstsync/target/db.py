"""The target database.

SQLite by default (stdlib, so tests and CI need no services), Postgres when the DSN says
so (needs the `postgres` extra). The DDL is generated from TARGET_SCHEMA, the same
structure the dry-run validates against, so the three views of the schema — Python,
SQLite, Postgres — cannot drift apart silently.

Writes are upserts on (tenant_id, external_id): loading the same records twice updates
them in place and never duplicates. That is what makes the whole migration re-runnable.
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path
from typing import Any

from firstsync.target.schema import TARGET_SCHEMA

# Each connection handle maps to one tenant, deterministically.
_TENANT_NS = uuid.UUID("3b2d9d55-6f2a-4bb0-9f52-a1b2c3d4e5f6")

SQL_TYPES = {
    "text": "text",
    "email": "text",
    "enum": "text",
    "date": "text",
    "timestamp": "text",
    "numeric": "real",
}


def tenant_id(connection: str) -> str:
    return str(uuid.uuid5(_TENANT_NS, connection))


def ddl() -> list[str]:
    """CREATE TABLE statements generated from TARGET_SCHEMA (SQLite dialect)."""
    statements = []
    for table, spec in TARGET_SCHEMA["tables"].items():
        columns = ["tenant_id text NOT NULL"]
        for field in spec["fields"]:
            null = " NOT NULL" if field["required"] else ""
            columns.append(f"{field['name']} {SQL_TYPES[field['type']]}{null}")
        columns.append("UNIQUE (tenant_id, external_id)")
        statements.append(
            f"CREATE TABLE IF NOT EXISTS {table} (\n    " + ",\n    ".join(columns) + "\n)"
        )
    return statements


class TargetDB:
    """A thin writer over the target database. SQLite file path, or ':memory:'."""

    def __init__(self, path: str | Path):
        self._conn = sqlite3.connect(str(path))
        self._conn.execute("PRAGMA foreign_keys = ON")
        for statement in ddl():
            self._conn.execute(statement)
        self._conn.commit()

    def upsert(self, table: str, tenant: str, row: dict[str, Any]) -> str:
        """Insert or update one row; returns 'inserted', 'updated' or 'unchanged'."""
        if table not in TARGET_SCHEMA["tables"]:
            raise ValueError(f"No such target table: {table!r}.")
        names = [f["name"] for f in TARGET_SCHEMA["tables"][table]["fields"]]
        values = {n: row.get(n) for n in names}
        existing = self._conn.execute(
            f"SELECT {', '.join(names)} FROM {table} WHERE tenant_id = ? AND external_id = ?",
            (tenant, values["external_id"]),
        ).fetchone()
        if existing is not None and list(existing) == [values[n] for n in names]:
            return "unchanged"
        placeholders = ", ".join("?" for _ in names)
        updates = ", ".join(f"{n} = excluded.{n}" for n in names if n != "external_id")
        self._conn.execute(
            f"INSERT INTO {table} (tenant_id, {', '.join(names)}) "
            f"VALUES (?, {placeholders}) "
            f"ON CONFLICT (tenant_id, external_id) DO UPDATE SET {updates}",
            (tenant, *[values[n] for n in names]),
        )
        return "updated" if existing is not None else "inserted"

    def count(self, table: str, tenant: str) -> int:
        if table not in TARGET_SCHEMA["tables"]:
            raise ValueError(f"No such target table: {table!r}.")
        result = self._conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE tenant_id = ?", (tenant,)
        )
        return int(result.fetchone()[0])

    def external_ids(self, table: str, tenant: str) -> set[str]:
        """Every external_id already loaded into one table for one tenant."""
        if table not in TARGET_SCHEMA["tables"]:
            raise ValueError(f"No such target table: {table!r}.")
        rows = self._conn.execute(
            f"SELECT external_id FROM {table} WHERE tenant_id = ?", (tenant,)
        )
        return {str(r[0]) for r in rows.fetchall()}

    def commit(self) -> None:
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
