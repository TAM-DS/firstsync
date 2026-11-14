"""Typed configuration.

Every setting FirstSync reads from the environment is declared here, with its type and
default, and validated when it is read. Nothing else in the package calls os.environ for
a FIRSTSYNC_ variable. Credentials are deliberately not here: Salesforce tokens are read
only by the client that needs them, and the Anthropic key only by the Agent SDK.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# One ID per process unless FIRSTSYNC_RUN_ID is set, so a parent process and the MCP
# server it starts can share one.
_PROCESS_RUN_ID = uuid.uuid4().hex[:12]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FIRSTSYNC_", extra="ignore")

    state_dir: Path = Path(".firstsync")
    audit_log: Path = Path(".firstsync/audit.jsonl")
    orgs_dir: Path | None = None
    run_id: str = Field(default=_PROCESS_RUN_ID, min_length=1, max_length=64)
    max_tool_calls: int = Field(default=300, ge=1, le=10_000)
    model: str | None = None
    portal_port: int = Field(default=8000, ge=1, le=65_535)


def get_settings() -> Settings:
    """Read the settings now. Not cached, so a changed environment is always honoured."""
    return Settings()
