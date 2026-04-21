#!/usr/bin/env python3
"""
The Danual — Auditor (Phase 2.5)
Classifies user-created skills as likely_junk, suspect, legitimate, or exempt.

Hermes's `skills.creation_nudge_interval` can produce narrative/diary skills —
one-time troubleshooting notes saved as reusable workflows. This phase flags
those with heuristics so the renderer can badge them and a future quarantine
tool can move them without deleting. Detection-only: never mutates user skills.

Input:  output/manifest.json (produced by scanner + enricher)
Output: manifest.json augmented with per-skill `audit` fields, plus a
        standalone output/skill_audit.json for quarantine tooling.
"""

import json
import os
import re
import logging
from datetime import datetime, timezone
from pathlib import Path

HERMES_HOME = Path.home() / ".hermes"
SKILLS_DIR = HERMES_HOME / "skills"
SCRIPT_DIR = Path(__file__).parent
OUTPUT_DIR = SCRIPT_DIR.parent / "output"
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"
AUDIT_PATH = OUTPUT_DIR / "skill_audit.json"

logging.basicConfig(level=logging.INFO, format="  %(message)s")
log = logging.getLogger("danual-auditor")


# ─── Thresholds ───────────────────────────────────────────────────────────────
# Score ≥ LIKELY_JUNK ⇒ likely_junk, ≥ SUSPECT ⇒ suspect, else legitimate.
LIKELY_JUNK = 60
SUSPECT = 30


def _atomic_write(path: Path, content: str) -> None:
    """Write via temp-file + os.replace so concurrent readers never see a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


# ─── Heuristic Patterns ───────────────────────────────────────────────────────

# Inline narrative / diary-like language
NARRATIVE_PATTERNS = [
    re.compile(r"\bwe (looked|found|noticed|saw|ran|tried|checked|discovered|got|learned|wanted)\b", re.IGNORECASE),
    re.compile(r"\bI (noticed|saw|ran|looked|tried|found|checked|observed|got)\b"),
    re.compile(r"\bturns? out\b", re.IGNORECASE),
    re.compile(r"\btoday('s|\s)", re.IGNORECASE),
    re.compile(r"\byesterday\b", re.IGNORECASE),
    re.compile(r"\bthis (morning|afternoon|evening)\b", re.IGNORECASE),
    re.compile(r"\blast (week|night|month)\b", re.IGNORECASE),
    re.compile(r"\bwhen we (ran|checked|looked|tried)\b", re.IGNORECASE),
    re.compile(r"\b(verdict)s?\s*(for|:)", re.IGNORECASE),
    re.compile(r"\*\*Verdict\b", re.IGNORECASE),
    re.compile(r"^\*\*The fix:?\*\*", re.MULTILINE | re.IGNORECASE),
]

# Dates / specific times in prose that bolt a skill to one moment
DATED_PATTERNS = [
    re.compile(r"\b20\d{2}-\d{2}-\d{2}\b"),
    re.compile(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}(?!\d)"),
    re.compile(r"\b\d{1,2}(?::\d{2})?\s*(AM|PM)\b"),
    re.compile(r"\b(yesterday|tomorrow|last (?:week|month|night)|this (?:morning|week))\b", re.IGNORECASE),
]

# Verdict / summary / opinion markers
OPINION_PATTERNS = [
    re.compile(r"\b(it seems|I think|my (recommendation|take|opinion)|bottom line|overall,|in retrospect)\b", re.IGNORECASE),
    re.compile(r"^#{2,4}\s*Key\s+(Insight|Finding|Takeaway|Lesson)s?\b", re.MULTILINE | re.IGNORECASE),
    re.compile(r"\bkey (insight|finding|takeaway|lesson)\b", re.IGNORECASE),
]

# Date-bound numeric facts
STATIC_OBS_PATTERNS = [
    re.compile(r"\$\d+(?:\.\d+)?[kKmM]?(?![\w/])"),
    re.compile(r"\b\d+\s*(calls?|requests?|errors?|messages|rows?|tokens?|files?|records?|events?)\b", re.IGNORECASE),
    re.compile(r"\b\d+(?:\.\d+)?\s*(seconds?|minutes?|hours?|days?)\s+(old|ago|later|of|elapsed)\b", re.IGNORECASE),
    re.compile(r"\b\d{2,}(?:\.\d+)?%\b"),
]

# Descriptive H2/H3 headings (as opposed to procedural ones)
NARRATIVE_HEADING_PATTERNS = [
    re.compile(r"^#{2,3}\s*(Context|Background|Overview|Summary|Problem|Symptoms|Issue|Situation)\s*$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^#{2,3}\s*The\s+[A-Z][\w-]*(?:\s+[A-Z]?[\w-]*){0,4}(?:Trap|Catch|Gotcha|Fix|Verdict|Problem|Issue|Bug|Finding)\b", re.MULTILINE),
    re.compile(r"^#{2,3}\s*(The Fix|The Verdict|The Problem|The Issue|The Catch|The Trap|The Gotcha)\b", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^#{2,3}\s*(Old approach|New approach|What we found|What happened|What I found)\b", re.MULTILINE | re.IGNORECASE),
]

# Comparison tables — markdown pipe rows or box-drawing rules
COMPARISON_TABLE_PATTERNS = [
    re.compile(r"^[┌┬└┴├┤]", re.MULTILINE),
    re.compile(r"^\s*\|[^\n]*\|[^\n]*\|[^\n]*$", re.MULTILINE),
]

# Code / command evidence — presence negates no_commands flag
CODE_PATTERNS = [
    re.compile(r"```[a-zA-Z]*\n"),
    re.compile(r"`[^`\n]{2,}\.(py|sh|yaml|yml|json|js|ts|go|rs|md)`"),
    re.compile(r"`~/[^`\n]*`"),
    re.compile(r"`[./][^`\n]{2,}`"),
    re.compile(r"`[A-Za-z_][\w-]*\([^`\n]*\)`"),
]


# ─── Workflow & Trigger Detectors ─────────────────────────────────────────────

def _has_workflow(body: str) -> bool:
    """True if the skill body looks procedural (steps, numbered sections, usage)."""
    if re.search(
        r"^#{2,3}\s*(Workflow|Usage|Steps?|How to|How it works|Procedure|Process|Practical discovery steps|Verification steps|Core workflow)\b",
        body, re.MULTILINE | re.IGNORECASE,
    ):
        return True
    if len(re.findall(r"^#{2,3}\s*Step\s*\d+", body, re.MULTILINE | re.IGNORECASE)) >= 2:
        return True
    if len(re.findall(r"^#{2,3}\s*\d+\.\s+\S", body, re.MULTILINE)) >= 2:
        return True
    if len(re.findall(r"^\s*\d+\.\s+\S", body, re.MULTILINE)) >= 3:
        return True
    return False


def _has_trigger(body: str) -> bool:
    """True if the skill body declares when it should activate."""
    for pattern in (
        r"^#{2,3}\s*When (?:to use this|this skill|this is|you should|I should)",
        r"^#{2,3}\s*Usage\b",
        r"^#{2,3}\s*What this skill is for\b",
        r"\bUse this (when|for|to)\b",
        r"\bgood fit (for|when)\b",
        r"\b(activate|invoke|trigger) this skill when\b",
    ):
        if re.search(pattern, body, re.MULTILINE | re.IGNORECASE):
            return True
    return False


def _has_code(body: str) -> bool:
    return any(p.search(body) for p in CODE_PATTERNS)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _split_frontmatter(text: str):
    """Return (frontmatter_text, body_text). Empty frontmatter if absent."""
    if not text.startswith("---"):
        return "", text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return "", text
    return parts[1], parts[2]


def _parse_frontmatter(fm_text: str) -> dict:
    """Best-effort YAML parse. Falls back to regex for do_not_audit when yaml is unavailable."""
    if not fm_text.strip():
        return {}
    try:
        import yaml
        return yaml.safe_load(fm_text) or {}
    except Exception:
        meta = {}
        for line in fm_text.splitlines():
            if re.match(r"^\s*do_not_audit\s*:\s*(true|yes)\s*$", line, re.IGNORECASE):
                meta["do_not_audit"] = True
        return meta


def _first_snippet(patterns, text: str, context: int = 60) -> str:
    """Return the first matched text, trimmed to a readable snippet."""
    for p in patterns:
        m = p.search(text)
        if m:
            start = max(0, m.start() - 10)
            end = min(len(text), m.end() + context)
            return text[start:end].strip().replace("\n", " ")[:140]
    return ""


def _count(patterns, text: str) -> int:
    return sum(len(p.findall(text)) for p in patterns)


def _count_date_in_code(body: str) -> int:
    """Count date/time matches that fall inside fenced code blocks."""
    count = 0
    in_fence = False
    for line in body.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            for p in DATED_PATTERNS:
                count += len(p.findall(line))
    return count


# ─── Auditor ──────────────────────────────────────────────────────────────────

def audit_skill_file(skill_md: Path):
    """Return (status, score, flags, frontmatter_meta) for a single SKILL.md."""
    text = skill_md.read_text(encoding="utf-8", errors="replace")
    fm_text, body = _split_frontmatter(text)
    body = body.strip()
    meta = _parse_frontmatter(fm_text)

    if meta.get("do_not_audit") is True:
        return "exempt", 0, [], meta

    flags = []
    score = 0

    # 1. Narrative phrases (25) — single fire; pick first for evidence
    if any(p.search(body) for p in NARRATIVE_PATTERNS):
        score += 25
        snippet = _first_snippet(NARRATIVE_PATTERNS, body) or "diary-like language"
        flags.append({"type": "narrative_phrase", "evidence": snippet})

    # 2. Dated facts (20 if ≥3, 10 if 1-2) — excludes frontmatter, body only
    dated_count = _count(DATED_PATTERNS, body)
    if dated_count >= 3:
        score += 20
        flags.append({
            "type": "dated_fact",
            "evidence": f"{dated_count} date/time references in body " +
                        (f'(e.g., "{_first_snippet(DATED_PATTERNS, body, 30)}")' if dated_count else ""),
        })
    elif dated_count > 0:
        score += 10
        flags.append({
            "type": "dated_fact",
            "evidence": f"{dated_count} date/time reference(s) in body " +
                        f'(e.g., "{_first_snippet(DATED_PATTERNS, body, 30)}")',
        })

    # 2b. Dates embedded in commands (+15) — skill is date-locked
    date_in_code = _count_date_in_code(body)
    if date_in_code >= 2:
        score += 15
        flags.append({
            "type": "dated_fact_in_commands",
            "evidence": f"{date_in_code} dates hard-coded inside shell commands (skill is date-locked)",
        })

    # 3. No workflow structure (20)
    if not _has_workflow(body):
        score += 20
        flags.append({
            "type": "no_workflow_structure",
            "evidence": "no numbered steps, Workflow/Usage/Steps heading, or Step N sections",
        })

    # 4. No commands / code (15)
    if not _has_code(body):
        score += 15
        flags.append({
            "type": "no_commands",
            "evidence": "no code blocks, paths, or command references",
        })

    # 5. No trigger conditions (15)
    if not _has_trigger(body):
        score += 15
        flags.append({
            "type": "no_trigger_conditions",
            "evidence": "no 'When to use' / 'Use this when' / 'Usage' section",
        })

    # 6. Opinion / summary language (10)
    if any(p.search(body) for p in OPINION_PATTERNS):
        score += 10
        flags.append({
            "type": "opinion_summary",
            "evidence": _first_snippet(OPINION_PATTERNS, body) or "verdict/key-insight language",
        })

    # 7. Short body (10)
    if len(body) < 500:
        score += 10
        flags.append({
            "type": "short_body",
            "evidence": f"body under 500 chars ({len(body)})",
        })

    # 8. Static observations (15) — need ≥2 to distinguish from a stray number
    static_count = _count(STATIC_OBS_PATTERNS, body)
    if static_count >= 2:
        score += 15
        flags.append({
            "type": "static_observations",
            "evidence": f"{static_count} specific numeric facts (counts, $, percentages)",
        })

    # 9. Narrative headings (15)
    if any(p.search(body) for p in NARRATIVE_HEADING_PATTERNS):
        score += 15
        flags.append({
            "type": "narrative_headings",
            "evidence": _first_snippet(NARRATIVE_HEADING_PATTERNS, body, 30) or "descriptive headings",
        })

    # 10. Comparison tables (10) — ≥3 rows to rule out a single decoration
    table_rows = _count(COMPARISON_TABLE_PATTERNS, body)
    if table_rows >= 3:
        score += 10
        flags.append({
            "type": "comparison_table",
            "evidence": f"{table_rows} comparison-table rows (informational, not procedural)",
        })

    score = min(score, 100)
    if score >= LIKELY_JUNK:
        status = "likely_junk"
    elif score >= SUSPECT:
        status = "suspect"
    else:
        status = "legitimate"

    return status, score, flags, meta


def _find_user_skill_paths(user_skills) -> dict:
    """Map skill name → Path(SKILL.md). Uses frontmatter name, falls back to dir name."""
    wanted = {s.get("name") for s in user_skills if s.get("name")}
    paths = {}
    for md in SKILLS_DIR.rglob("SKILL.md"):
        text = md.read_text(encoding="utf-8", errors="replace")
        fm_text, _ = _split_frontmatter(text)
        meta = _parse_frontmatter(fm_text)
        name = meta.get("name") or md.parent.name
        if name in wanted:
            paths[name] = md
    return paths


def audit():
    if not MANIFEST_PATH.exists():
        log.error("No manifest.json found — run the scanner first.")
        return

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    user_skills = manifest.get("user_guide", {}).get("skills", {}).get("user_created", [])

    summary = {"likely_junk": 0, "suspect": 0, "legitimate": 0, "exempt": 0}
    flagged_skills = []

    if not user_skills:
        log.info("No user-created skills to audit.")
    else:
        paths = _find_user_skill_paths(user_skills)
        for skill in user_skills:
            name = skill.get("name", "")
            skill_md = paths.get(name)
            if not skill_md:
                log.warning("No SKILL.md found for user skill: %s", name)
                continue

            status, score, flags, _meta = audit_skill_file(skill_md)
            skill["audit"] = {"status": status, "score": score, "flags": flags}
            summary[status] += 1

            if status in ("likely_junk", "suspect"):
                flagged_skills.append({
                    "name": name,
                    "path": str(skill_md.parent),
                    "status": status,
                    "score": score,
                    "flags": flags,
                })

        flagged_skills.sort(key=lambda s: s["score"], reverse=True)

    audit_doc = {
        "audited_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "flagged_skills": flagged_skills,
    }

    _atomic_write(MANIFEST_PATH, json.dumps(manifest, indent=2, ensure_ascii=False))
    _atomic_write(AUDIT_PATH, json.dumps(audit_doc, indent=2, ensure_ascii=False))

    log.info(
        "Audited %d user skills — %d likely_junk, %d suspect, %d legitimate, %d exempt",
        len(user_skills),
        summary["likely_junk"], summary["suspect"], summary["legitimate"], summary["exempt"],
    )


def main():
    log.info("═══ The Danual — Auditor ═══")
    log.info("")
    audit()
    log.info("Done — manifest.json and skill_audit.json updated.")


if __name__ == "__main__":
    main()
