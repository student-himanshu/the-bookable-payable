"""Tiny .env loader (no dependency). Real environment variables always win over the file.

    GEMINI_API_KEY=...        # or GOOGLE_API_KEY / ANTHROPIC_API_KEY
    BOOKABLE_MODEL=...        # optional model override
The file `.env` is git-ignored; commit only `.env.example`.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env(path: Path = ROOT / ".env") -> list:
    """Load KEY=VALUE lines into os.environ without overriding existing vars. -> keys set."""
    set_keys = []
    try:
        lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return set_keys
    for ln in lines:
        ln = ln.strip()
        if not ln or ln.startswith("#") or "=" not in ln:
            continue
        k, v = ln.split("=", 1)
        k = k.strip().removeprefix("export ").strip()
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        elif " #" in v:
            v = v.split(" #", 1)[0].strip()
        if k and v and k not in os.environ:
            os.environ[k] = v
            set_keys.append(k)
    return set_keys
