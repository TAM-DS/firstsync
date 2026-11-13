"""Load KEY=VALUE lines from a .env file into the environment, without overriding it."""

from __future__ import annotations

import os
from pathlib import Path


def load_dotenv(path: str | Path = ".env") -> list[str]:
    """Set variables from the file that are not already set. Returns the names it set."""
    file = Path(path)
    if not file.is_file():
        return []
    loaded = []
    for line in file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name, value = name.strip(), value.strip().strip("'\"")
        if name and value and name not in os.environ:
            os.environ[name] = value
            loaded.append(name)
    return loaded
