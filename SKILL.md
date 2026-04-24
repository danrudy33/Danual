---
name: danual
description: "The Danual — auto-generate a living, version-aware HTML manual for your Hermes instance. Scans tools, commands, CLI subcommands, skills, integrations, MCP servers, cron jobs, config, and env vars. Highlights new features per release (green) and recent user additions (blue, 30-day). Audits user-created skills for narrative/diary patterns and flags likely junk. Self-contained HTML with search, clickable explainers, and color-coded entries. Auto-rebuilds via gateway hook and nightly cron."
version: 3.1.0
metadata:
  hermes:
    tags: [documentation, devops, manual, tools, audit]
---

# The Danual — Dan's Dynamic-Manual for Hermes

A self-updating, browser-based HTML manual that regenerates after every Hermes update and nightly to catch local changes. Documents all tools, commands, CLI subcommands, skills, integrations, and configuration — highlighting what's new in each release and what's been recently added locally.

## Features

- **Full coverage**: 47 tools, 51 commands, 73 CLI subcommands, 90 skills, 19 platforms, 170 config options, 299 env vars, MCP servers, cron jobs, terminal backends
- **Self-contained HTML**: Single file, inline CSS/JS, no external dependencies
- **Real-time search**: Filter across all sections as you type
- **Click-to-explain modals**: Every item is clickable — what it does, why it matters, example use case
- **Dual badge system**:
  - ✨ **NEW in vX.X** (green): Items from a Hermes version update, cleared on next update
  - 🆕 **Recently Added** (blue): User/local items, persists 30 days regardless of updates
  - Override the 30-day window by adding `danual: { recently_added_days: N }` to `~/.hermes/config.yaml`
- **Cascade detection**: New platforms auto-flag their env vars and config options
- **Source distinction**: `[Hermes]` bundled vs `[You]` user-created, color-coded
- **Release history**: Full release notes with clickable scrollable modals
- **Auto-rebuild**: Gateway startup hook (post-update) + nightly cron (local additions)
- **Enrichment caching**: `--no-enrich` preserves previously generated explainers
- **Skill audit** (v3.1.0): Flags user-created skills that look like narrative troubleshooting notes instead of reusable procedures
  - 🔴 **Likely Junk** (score ≥ 60): dated facts, narrative headings, no workflow/trigger structure
  - 🟡 **Suspect** (score 30–59): mixed signals — review before relying
  - 🟢 **Legitimate** (score < 30): workflow + trigger + commands present
  - ⚪ **Exempt**: add `do_not_audit: true` to a skill's frontmatter to whitelist it
  - Detection only — never mutates user skills. Writes `output/skill_audit.json` for a future quarantine tool.
  - Click any badge in the manual to see the specific flags that fired.

## Usage

```bash
# Full pipeline: scan → diff → enrich → render
~/.hermes/skills/devops/danual/scripts/update_manual.sh

# Quick re-render (skip enrichment, uses cached explainers)
~/.hermes/skills/devops/danual/scripts/update_manual.sh --no-enrich

# Scan only (just produce manifest.json)
~/.hermes/skills/devops/danual/scripts/update_manual.sh --scan-only
```

## Auto-Rebuild Triggers

1. **Gateway startup hook** (`~/.hermes/hooks/danual-rebuild/`): Fires after every gateway restart (including post-`hermes update`). Full rebuild on version change, quick rebuild otherwise.
2. **Nightly cron** (`Danual Nightly Rebuild`, 4 AM ET): Quick rebuild to detect user-created skills, MCP servers, cron jobs added between updates. Reports to Telegram only if new items found.

## Output

- **Manual**: `~/.hermes/docs/Hermes_Manual.html` (also `Danual.html` symlink)
- **Manifest**: `~/.hermes/skills/devops/danual/output/manifest.json`

## Architecture

```
update_manual.sh (wrapper)
    │
    ├── regenerate_manual.py  ← Scanner: extracts all data → manifest.json
    ├── diff_manifest.py      ← Differ: version diff + local additions + cascade
    ├── enrich_manifest.py    ← Enricher: section intros + explainers
    ├── audit_skills.py       ← Auditor: heuristic junk detection on user skills
    └── render_manual.py      ← Renderer: self-contained HTML

hooks/danual-rebuild/        ← Gateway startup hook (post-update trigger)
scripts/danual_nightly.py    ← Cron helper (nightly local-additions scan)
```

## Files

```
scripts/
├── regenerate_manual.py   # Scanner (requires Hermes venv Python 3.11)
├── diff_manifest.py       # Differ (version + local + cascade + recently_added)
├── enrich_manifest.py     # Enricher (platforms, config, CLI, tools, skills)
├── audit_skills.py        # Auditor (narrative/diary heuristics on user skills)
├── render_manual.py       # HTML Renderer (dark theme, modals, dual badges, audit UI)
└── update_manual.sh       # Orchestrator wrapper
output/
├── manifest.json            # Current manifest (includes per-skill audit field)
├── skill_audit.json         # Standalone audit — consumed by quarantine tooling
└── .manifest_snapshot.json  # Previous manifest (diff baseline)
```
