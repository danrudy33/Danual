#!/usr/bin/env python3
"""Regression test for the differ's version-change, carry-forward, and cascade logic.

Builds synthetic manifest + snapshot fixtures in a temp directory, runs the real
differ against them, and asserts expected flag outcomes. Exits 0 on pass, 1 on fail.

Never touches the real manifest.json or snapshot — all fixtures live in tempdirs.

Run:
    python3 scripts/_test_version_change.py
"""

import json
import logging
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

import diff_manifest

# Silence the differ's log output so test output stays readable.
logging.getLogger("danual-differ").setLevel(logging.CRITICAL)


def _fixture_item(name, key="name", extra=None):
    item = {
        key: name,
        "description": "",
        "source": "hermes",
        "is_new": False,
        "explainer": {"what_it_does": "", "why_it_matters": "", "example_use_case": ""},
    }
    if extra:
        item.update(extra)
    return item


def _make_manifest(version):
    return {
        "platform": "hermes",
        "version": version,
        "previous_version": None,
        "user_guide": {
            "tools": [], "commands": [], "cli_subcommands": [],
            "skills": {"bundled": [], "user_created": []},
            "integrations": [],
        },
        "technical_reference": {
            "config_options": [], "environment_variables": [],
            "mcp_servers": [], "cron_jobs": [], "terminal_backends": [],
        },
        "release_notes": [],
        "section_intros": {},
    }


def _run_diff(snapshot, manifest):
    """Point diff_manifest at temp files, run it, return the resulting manifest."""
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        m_path = out / "manifest.json"
        s_path = out / ".manifest_snapshot.json"
        c_path = out / "config.yaml"  # doesn't exist → default 30d
        m_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        s_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")

        saved = (diff_manifest.MANIFEST_PATH, diff_manifest.SNAPSHOT_PATH,
                 diff_manifest.OUTPUT_DIR, diff_manifest.CONFIG_PATH)
        try:
            diff_manifest.MANIFEST_PATH = m_path
            diff_manifest.SNAPSHOT_PATH = s_path
            diff_manifest.OUTPUT_DIR = out
            diff_manifest.CONFIG_PATH = c_path
            diff_manifest.diff_manifest()
            return json.loads(m_path.read_text(encoding="utf-8"))
        finally:
            (diff_manifest.MANIFEST_PATH, diff_manifest.SNAPSHOT_PATH,
             diff_manifest.OUTPUT_DIR, diff_manifest.CONFIG_PATH) = saved


FAILURES = []


def check(label, cond, detail=""):
    status = "✓" if cond else "✗"
    line = f"  {status} {label}"
    if not cond and detail:
        line += f"  ({detail})"
    print(line)
    if not cond:
        FAILURES.append(label + (f": {detail}" if detail else ""))


# ─── Scenario 1: version bump 0.8.9 → 0.9.0 ───────────────────────────────────
print("Scenario 1: version bump 0.8.9 → 0.9.0")
snap = _make_manifest("0.8.9")
curr = _make_manifest("0.9.0")

# Shared baseline — present in both
snap["user_guide"]["tools"].append(_fixture_item("existing_tool"))
curr["user_guide"]["tools"].append(_fixture_item("existing_tool"))

# New items in 0.9.0 — absent from snapshot
curr["user_guide"]["tools"].append(_fixture_item("web_search"))
curr["user_guide"]["commands"].append(_fixture_item("/cron"))
curr["user_guide"]["integrations"].append(
    _fixture_item("telegram", key="key", extra={"name": "Telegram"}))

# Env vars present in both — should cascade because telegram is newly added
for name in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_REACTIONS"):
    snap["technical_reference"]["environment_variables"].append(_fixture_item(name))
    curr["technical_reference"]["environment_variables"].append(_fixture_item(name))

# Unrelated env var — cascade must NOT over-reach
snap["technical_reference"]["environment_variables"].append(_fixture_item("UNRELATED_VAR"))
curr["technical_reference"]["environment_variables"].append(_fixture_item("UNRELATED_VAR"))

# Plant a recently_added flag in snapshot — must be cleared on version change
snap["user_guide"]["skills"]["user_created"].append(_fixture_item(
    "my_skill",
    extra={"recently_added": True, "added_at": "2026-04-15T00:00:00+00:00", "source": "user"}))
curr["user_guide"]["skills"]["user_created"].append(
    _fixture_item("my_skill", extra={"source": "user"}))

result = _run_diff(snap, curr)

tools = {t["name"]: t for t in result["user_guide"]["tools"]}
cmds = {c["name"]: c for c in result["user_guide"]["commands"]}
integs = {i["key"]: i for i in result["user_guide"]["integrations"]}
evs = {e["name"]: e for e in result["technical_reference"]["environment_variables"]}
my_skill = next(s for s in result["user_guide"]["skills"]["user_created"] if s["name"] == "my_skill")

check("previous_version set to 0.8.9",
      result.get("previous_version") == "0.8.9", f"got {result.get('previous_version')!r}")
check("new tool web_search flagged is_new=True",
      tools["web_search"].get("is_new") is True)
check("web_search added_in_version=0.9.0",
      tools["web_search"].get("added_in_version") == "0.9.0",
      f"got {tools['web_search'].get('added_in_version')!r}")
check("existing tool stays is_new=False",
      tools["existing_tool"].get("is_new") is False,
      f"got {tools['existing_tool'].get('is_new')!r}")
check("new command /cron flagged is_new=True",
      cmds["/cron"].get("is_new") is True)
check("new platform telegram flagged is_new=True",
      integs["telegram"].get("is_new") is True)
check("cascade: TELEGRAM_BOT_TOKEN auto-flagged via platform",
      evs["TELEGRAM_BOT_TOKEN"].get("is_new") is True)
check("cascade: TELEGRAM_REACTIONS auto-flagged",
      evs["TELEGRAM_REACTIONS"].get("is_new") is True)
check("cascade does NOT over-reach: UNRELATED_VAR stays is_new=False",
      evs["UNRELATED_VAR"].get("is_new") is False,
      f"got {evs['UNRELATED_VAR'].get('is_new')!r}")
check("recently_added cleared on version change",
      not my_skill.get("recently_added"),
      f"got {my_skill.get('recently_added')!r}")

# ─── Scenario 2: same-version run — carry forward + detect local additions ───
print()
print("Scenario 2: same-version run carries flags forward + detects local additions")
snap2 = _make_manifest("0.9.0")
curr2 = _make_manifest("0.9.0")

# Item flagged green in prior run — must stay green on carry-forward
snap2["user_guide"]["tools"].append(_fixture_item(
    "web_search", extra={"is_new": True, "added_in_version": "0.9.0"}))
curr2["user_guide"]["tools"].append(_fixture_item("web_search"))

# Pre-existing user skill (not newly added)
snap2["user_guide"]["skills"]["user_created"].append(
    _fixture_item("old_user_skill", extra={"source": "user"}))
curr2["user_guide"]["skills"]["user_created"].append(
    _fixture_item("old_user_skill", extra={"source": "user"}))

# Brand-new user skill (not in snapshot) — must be flagged recently_added
curr2["user_guide"]["skills"]["user_created"].append(
    _fixture_item("brand_new_skill", extra={"source": "user"}))

result2 = _run_diff(snap2, curr2)
tools2 = {t["name"]: t for t in result2["user_guide"]["tools"]}
skills2 = {s["name"]: s for s in result2["user_guide"]["skills"]["user_created"]}

check("carry-forward: web_search keeps is_new=True",
      tools2["web_search"].get("is_new") is True)
check("carry-forward: web_search keeps added_in_version=0.9.0",
      tools2["web_search"].get("added_in_version") == "0.9.0")
check("local addition: brand_new_skill flagged recently_added=True",
      skills2["brand_new_skill"].get("recently_added") is True)
check("local addition: brand_new_skill has added_at timestamp",
      isinstance(skills2["brand_new_skill"].get("added_at"), str)
      and len(skills2["brand_new_skill"]["added_at"]) > 10)
check("pre-existing skill NOT flagged recently_added",
      not skills2["old_user_skill"].get("recently_added"),
      f"got {skills2['old_user_skill'].get('recently_added')!r}")

# ─── Summary ──────────────────────────────────────────────────────────────────
print()
if FAILURES:
    print(f"✗ {len(FAILURES)} assertion(s) failed:")
    for f in FAILURES:
        print(f"   - {f}")
    sys.exit(1)
print("✓ All assertions passed.")
sys.exit(0)
