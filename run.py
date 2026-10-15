"""The single documented command:

    python run.py                          # documents/ -> output/  (OCR + rules; + vision rescue if a key is set)
    python run.py --docs <folder> --out <folder>
    python run.py --no-llm                 # rules only, fully offline

Vision rescue (Gemini or Claude) is used automatically when GEMINI_API_KEY / ANTHROPIC_API_KEY is
present in the environment or in .env; otherwise the run is rules-only and says so.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from bookable.config import load_env
from bookable.phase3 import main as phase3_main


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    load_env()
    no_llm = "--no-llm" in argv
    argv = [a for a in argv if a != "--no-llm"]
    has_key = any(os.environ.get(k) for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY"))
    if not no_llm and has_key and "--llm" not in argv:
        argv.append("--llm")
    elif not no_llm and not has_key:
        print("note: no API key found - running rules-only (set GEMINI_API_KEY in .env for vision rescue)",
              file=sys.stderr)
    return phase3_main(argv)


if __name__ == "__main__":
    sys.exit(main())
