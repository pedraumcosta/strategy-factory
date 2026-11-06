"""The one place vendor keys live: a gitignored .env at the repo root.

The CLI and the tools/ runners call load_env() at startup, so a key put in
.env once is seen by every entry point — no per-shell exports. A variable
already set in the environment always wins: .env is the fallback, not an
override, so a one-off `KEY=... factory ...` still behaves as typed.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"


def load_env(path: Path = ENV_FILE, environ=os.environ) -> list[str]:
    """Load KEY=VALUE lines (comments, blanks and an optional `export `
    prefix allowed; single/double quotes around the value stripped).
    Returns the names actually set."""
    if not path.exists():
        return []
    loaded = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        name, _, value = line.partition("=")
        name, value = name.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        if name and name not in environ:
            environ[name] = value
            loaded.append(name)
    return loaded
