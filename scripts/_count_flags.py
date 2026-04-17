#!/usr/bin/env python3
"""Count is_new and recently_added flags across all sections of manifest.json.

Emits: "<new_count> <recent_count>" on stdout. Missing / malformed manifest → "0 0".
Used by update_manual.sh to produce the post-build summary.
"""

import json
import sys
from pathlib import Path

MANIFEST = Path(__file__).parent.parent / "output" / "manifest.json"


def main():
    try:
        m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except Exception:
        print("0 0")
        return

    sections = []
    ug = m.get("user_guide", {})
    tr = m.get("technical_reference", {})
    sections.append(ug.get("tools", []))
    sections.append(ug.get("commands", []))
    sections.append(ug.get("cli_subcommands", []))
    sections.append(ug.get("skills", {}).get("bundled", []))
    sections.append(ug.get("skills", {}).get("user_created", []))
    sections.append(ug.get("integrations", []))
    for sec in tr.values():
        if isinstance(sec, list):
            sections.append(sec)

    new = 0
    recent = 0
    for sec in sections:
        for item in sec:
            if item.get("is_new"):
                new += 1
            if item.get("recently_added"):
                recent += 1

    print(f"{new} {recent}")


if __name__ == "__main__":
    main()
