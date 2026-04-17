#!/usr/bin/env python3
"""Danual nightly rebuild — runs the pipeline and outputs a summary for the cron agent."""

import subprocess
import json
from pathlib import Path

SCRIPT = Path.home() / ".hermes/skills/devops/danual/scripts/update_manual.sh"
MANIFEST = Path.home() / ".hermes/skills/devops/danual/output/manifest.json"


def main():
    result = subprocess.run(
        ["bash", str(SCRIPT), "--no-enrich"],
        capture_output=True, text=True, timeout=120,
    )

    if result.returncode != 0:
        print(f"REBUILD FAILED (exit {result.returncode})")
        print(result.stderr[-500:] if result.stderr else "no stderr")
        return

    try:
        m = json.loads(MANIFEST.read_text())
    except Exception as e:
        print(f"Could not read manifest: {e}")
        return

    new_count = 0
    recent_count = 0
    recent_items = []

    all_sections = []
    ug = m.get("user_guide", {})
    tr = m.get("technical_reference", {})
    all_sections.extend([ug.get("tools", []), ug.get("commands", []),
                         ug.get("cli_subcommands", []),
                         ug.get("skills", {}).get("bundled", []),
                         ug.get("skills", {}).get("user_created", []),
                         ug.get("integrations", [])])
    for sec in tr.values():
        if isinstance(sec, list):
            all_sections.append(sec)

    for sec in all_sections:
        for item in sec:
            if item.get("is_new"):
                new_count += 1
            if item.get("recently_added"):
                recent_count += 1
                recent_items.append(item.get("name", item.get("key", "?")))

    print(f"version: {m.get('version', '?')}")
    print(f"version_new: {new_count}")
    print(f"recently_added: {recent_count}")
    if recent_items:
        print(f"recent_items: {', '.join(recent_items)}")
    print(f"status: ok")


if __name__ == "__main__":
    main()
