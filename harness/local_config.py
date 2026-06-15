#!/usr/bin/env python3
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENV = ROOT / "experiment" / "local.env"


def load_local_env(path=LOCAL_ENV):
    """Load repo-local harness defaults without overriding the shell."""
    loaded = {}
    if not path.exists():
        return loaded

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key:
            continue
        if key not in os.environ and value:
            os.environ[key] = value
            loaded[key] = value
    return loaded
