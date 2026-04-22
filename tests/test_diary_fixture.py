#!/usr/bin/env python3
"""
Regression guard — the synthetic diary fixture must still classify as
likely_junk after any heuristic tuning. If this fails, the auditor has
been relaxed too far and real diary skills will sneak through.
"""

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from audit_skills import audit_skill_file, LIKELY_JUNK  # noqa: E402

fixture = Path(__file__).parent / "fixtures" / "genuine_diary_skill.md"
status, score, flags, _meta = audit_skill_file(fixture)

print(f"genuine-diary-skill → {status} (score {score})")
print(f"  flags: {[f['type'] for f in flags]}")

assert status == "likely_junk", f"Expected likely_junk, got {status} (score {score})"
assert score >= LIKELY_JUNK, f"Score {score} below LIKELY_JUNK threshold {LIKELY_JUNK}"
print("PASS")
