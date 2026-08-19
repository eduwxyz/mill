#!/usr/bin/env -S uv run
# /// script
# dependencies = []
# ///
"""make_config — generate adws/adw_mill_config/mill.config.yaml with great defaults.

Usage:
    uv run <skill>/scripts/make_config.py [--force]
"""

import argparse
import shutil
import sys
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "mill.config.yaml"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    dest = Path.cwd() / "adws" / "adw_mill_config" / "mill.config.yaml"
    if dest.exists() and not args.force:
        print(f"{dest} already exists — use --force to overwrite")
        return 1
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(TEMPLATE, dest)
    print(f"wrote {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
