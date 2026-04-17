#!/usr/bin/env python3
"""
The Danual — Differ (Phase 2)
Compares current manifest against previous snapshot, flags new items.

Two badge systems:
  - is_new (green ✨): Items new in a Hermes version update. Cleared on next version change.
  - recently_added (blue 🆕): User/local items detected between versions. Time-based,
    default 30 days; override via `danual.recently_added_days` in ~/.hermes/config.yaml.
"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
OUTPUT_DIR = SCRIPT_DIR.parent / "output"
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"
SNAPSHOT_PATH = OUTPUT_DIR / ".manifest_snapshot.json"
CONFIG_PATH = Path.home() / ".hermes" / "config.yaml"

# Fallback used if config.yaml doesn't set danual.recently_added_days.
DEFAULT_RECENTLY_ADDED_DAYS = 30

# Must match SCHEMA_VERSION in regenerate_manual.py. Older snapshots without
# this field are treated as v1 for backward compatibility.
CURRENT_SCHEMA_VERSION = 1

# Items Danual creates about itself — never flag as recently_added (avoids
# the manual loudly announcing its own installation as a "new feature").
# Match by (section_key, item_key).
SELF_REFERENTIAL_ITEMS = {
    ("cron_jobs", "Danual Nightly Rebuild"),
}


def _atomic_write(path: Path, content: str) -> None:
    """Write via temp-file + os.replace so concurrent readers never see a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


logging.basicConfig(level=logging.INFO, format="  %(message)s")
log = logging.getLogger("danual-differ")


def _recently_added_days():
    """Return the configured recently-added window in days.

    Reads ~/.hermes/config.yaml for danual.recently_added_days (positive int).
    Falls back to DEFAULT_RECENTLY_ADDED_DAYS on missing key, malformed YAML,
    or invalid value.
    """
    if not CONFIG_PATH.exists():
        return DEFAULT_RECENTLY_ADDED_DAYS
    try:
        import yaml
        config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        val = (config.get("danual") or {}).get("recently_added_days")
        if val is None:
            return DEFAULT_RECENTLY_ADDED_DAYS
        if isinstance(val, bool) or not isinstance(val, int) or val < 1:
            log.warning("Invalid danual.recently_added_days (%r) — using default %d",
                        val, DEFAULT_RECENTLY_ADDED_DAYS)
            return DEFAULT_RECENTLY_ADDED_DAYS
        return val
    except Exception as exc:
        log.warning("Could not read config.yaml (%s) — using default %d",
                    exc, DEFAULT_RECENTLY_ADDED_DAYS)
        return DEFAULT_RECENTLY_ADDED_DAYS


def _all_sections(manifest):
    """Yield (items_list, key_field, section_key) for every section in the manifest.

    section_key is a stable string identifier used for cross-manifest flag lookups
    (replaces the prior id()-based matching, which was fragile when a key was missing).
    """
    ug = manifest.get("user_guide", {})
    tr = manifest.get("technical_reference", {})
    skills = ug.get("skills", {}) or {}
    yield ug.get("tools", []), "name", "tools"
    yield ug.get("commands", []), "name", "commands"
    yield ug.get("cli_subcommands", []), "name", "cli_subcommands"
    yield skills.get("bundled", []), "name", "skills_bundled"
    yield skills.get("user_created", []), "name", "skills_user"
    yield ug.get("integrations", []), "key", "integrations"
    yield tr.get("config_options", []), "key", "config_options"
    yield tr.get("environment_variables", []), "name", "environment_variables"
    yield tr.get("mcp_servers", []), "name", "mcp_servers"
    yield tr.get("cron_jobs", []), "name", "cron_jobs"
    yield tr.get("terminal_backends", []), "name", "terminal_backends"


def _extract_item_names(manifest):
    """Build a dict of section -> set of item names from a manifest."""
    names = {}
    ug = manifest.get("user_guide", {})
    tr = manifest.get("technical_reference", {})

    names["tools"] = {t["name"] for t in ug.get("tools", [])}
    names["commands"] = {c["name"] for c in ug.get("commands", [])}
    names["cli_subcommands"] = {c["name"] for c in ug.get("cli_subcommands", [])}
    names["skills_bundled"] = {s["name"] for s in ug.get("skills", {}).get("bundled", [])}
    names["skills_user"] = {s["name"] for s in ug.get("skills", {}).get("user_created", [])}
    names["integrations"] = {i.get("key", i["name"]) for i in ug.get("integrations", [])}
    names["config_options"] = {c["key"] for c in tr.get("config_options", [])}
    names["environment_variables"] = {e["name"] for e in tr.get("environment_variables", [])}
    names["mcp_servers"] = {s["name"] for s in tr.get("mcp_servers", [])}
    names["cron_jobs"] = {j["name"] for j in tr.get("cron_jobs", [])}
    names["terminal_backends"] = {b["name"] for b in tr.get("terminal_backends", [])}

    return names


def _flag_new_items(items, new_names, version, key_field="name"):
    """Mark items whose key_field value is in new_names."""
    count = 0
    for item in items:
        if item.get(key_field) in new_names:
            item["is_new"] = True
            item["added_in_version"] = version
            count += 1
        else:
            item["is_new"] = False
    return count


def diff_manifest():
    """Compare current manifest to snapshot and flag new items."""
    if not MANIFEST_PATH.exists():
        log.error("No manifest.json found — run the scanner first.")
        return None

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    current_version = manifest.get("version", "unknown")
    is_first_run = not SNAPSHOT_PATH.exists()
    now = datetime.now(timezone.utc).isoformat()

    if is_first_run:
        log.info("First run — establishing baseline (nothing marked as new)")
        _clear_all_flags(manifest)
        _save_snapshot(manifest)
        _atomic_write(MANIFEST_PATH, json.dumps(manifest, indent=2, ensure_ascii=False))
        return manifest

    previous = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))

    # Schema-version guard: if the saved snapshot was written by an incompatible
    # format, rebaseline instead of silently misinterpreting it.
    prev_schema = previous.get("schema_version", 1)
    if prev_schema != CURRENT_SCHEMA_VERSION:
        log.warning("Snapshot schema_version %s != current %s — rebaselining",
                    prev_schema, CURRENT_SCHEMA_VERSION)
        _clear_all_flags(manifest)
        _save_snapshot(manifest)
        _atomic_write(MANIFEST_PATH, json.dumps(manifest, indent=2, ensure_ascii=False))
        return manifest

    prev_version = previous.get("version", "unknown")

    if current_version == prev_version:
        log.info("Same version (%s) — preserving flags, checking for local additions", current_version)

        carried_new = _carry_forward_new_flags(manifest, previous)
        carried_recent = _carry_forward_recently_added(manifest, previous)
        _unflag_self_items(manifest)
        local_added = _detect_local_additions(manifest, previous, now)
        cascade_recent = _cascade_recently_added(manifest, now)
        manifest["previous_version"] = previous.get("previous_version")

        _save_snapshot(manifest)
        _atomic_write(MANIFEST_PATH, json.dumps(manifest, indent=2, ensure_ascii=False))
        log.info("Carried forward %d version-new + %d recently-added flags, %d new local additions (+%d cascaded)",
                 carried_new, carried_recent, local_added, cascade_recent)
        return manifest

    # ── Version change ──
    log.info("Diffing: %s → %s", prev_version, current_version)
    manifest["previous_version"] = prev_version

    prev_names = _extract_item_names(previous)
    curr_names = _extract_item_names(manifest)
    ug = manifest["user_guide"]
    tr = manifest["technical_reference"]

    total_new = 0

    new_tools = curr_names["tools"] - prev_names["tools"]
    total_new += _flag_new_items(ug["tools"], new_tools, current_version)
    log.info("  Tools: %d new (%s)", len(new_tools), ", ".join(sorted(new_tools)) if new_tools else "—")

    new_cmds = curr_names["commands"] - prev_names["commands"]
    total_new += _flag_new_items(ug["commands"], new_cmds, current_version)
    log.info("  Commands: %d new", len(new_cmds))

    new_cli = curr_names["cli_subcommands"] - prev_names.get("cli_subcommands", set())
    total_new += _flag_new_items(ug.get("cli_subcommands", []), new_cli, current_version)
    log.info("  CLI subcommands: %d new", len(new_cli))

    new_skills_b = curr_names["skills_bundled"] - prev_names["skills_bundled"]
    total_new += _flag_new_items(ug["skills"]["bundled"], new_skills_b, current_version)
    log.info("  Bundled skills: %d new", len(new_skills_b))

    new_integ = curr_names["integrations"] - prev_names["integrations"]
    total_new += _flag_new_items(ug["integrations"], new_integ, current_version, key_field="key")
    log.info("  Integrations: %d new", len(new_integ))

    new_cfg = curr_names["config_options"] - prev_names["config_options"]
    total_new += _flag_new_items(tr["config_options"], new_cfg, current_version, key_field="key")
    log.info("  Config options: %d new", len(new_cfg))

    new_env = curr_names["environment_variables"] - prev_names["environment_variables"]
    total_new += _flag_new_items(tr["environment_variables"], new_env, current_version)
    log.info("  Env vars: %d new", len(new_env))

    new_mcp = curr_names["mcp_servers"] - prev_names["mcp_servers"]
    total_new += _flag_new_items(tr["mcp_servers"], new_mcp, current_version)
    log.info("  MCP servers: %d new", len(new_mcp))

    new_cron = curr_names["cron_jobs"] - prev_names["cron_jobs"]
    total_new += _flag_new_items(tr["cron_jobs"], new_cron, current_version)
    log.info("  Cron jobs: %d new", len(new_cron))

    new_term = curr_names["terminal_backends"] - prev_names["terminal_backends"]
    total_new += _flag_new_items(tr["terminal_backends"], new_term, current_version)
    log.info("  Terminal backends: %d new", len(new_term))

    cascade = _cascade_new_flags(manifest, current_version)
    total_new += cascade

    # Clear any recently_added flags — version change resets the user-additions slate
    for items, _, _ in _all_sections(manifest):
        for item in items:
            item.pop("recently_added", None)
            item.pop("added_at", None)

    log.info("")
    log.info("Total new items: %d (including %d cascaded)", total_new, cascade)

    _save_snapshot(manifest)
    _atomic_write(MANIFEST_PATH, json.dumps(manifest, indent=2, ensure_ascii=False))
    return manifest


def _cascade_new_flags(manifest, version):
    """Auto-flag related items when a parent feature is new.

    Rules:
      - New platform integration → flag env vars matching the platform key pattern
      - New tool → flag config options under auxiliary.<tool_name>.*
      - New platform integration → flag config under <platform_key>.*
    """
    ug = manifest.get("user_guide", {})
    tr = manifest.get("technical_reference", {})
    cascaded = 0

    new_platform_keys = set()
    for integ in ug.get("integrations", []):
        if integ.get("is_new"):
            new_platform_keys.add(integ.get("key", "").lower())

    new_tool_names = set()
    for tool in ug.get("tools", []):
        if tool.get("is_new"):
            new_tool_names.add(tool["name"].lower())

    if new_platform_keys or new_tool_names:
        for ev in tr.get("environment_variables", []):
            if ev.get("is_new"):
                continue
            name_lower = ev["name"].lower()
            for pk in new_platform_keys:
                if name_lower.startswith(pk + "_") or name_lower.startswith(pk.replace("_", "") + "_"):
                    ev["is_new"] = True
                    ev["added_in_version"] = version
                    cascaded += 1
                    break

        for opt in tr.get("config_options", []):
            if opt.get("is_new"):
                continue
            key_lower = opt["key"].lower()
            for tn in new_tool_names:
                if key_lower.startswith(f"auxiliary.{tn}."):
                    opt["is_new"] = True
                    opt["added_in_version"] = version
                    cascaded += 1
                    break
            else:
                for pk in new_platform_keys:
                    if key_lower.startswith(pk + ".") or key_lower.startswith(pk.replace("_", "") + "."):
                        opt["is_new"] = True
                        opt["added_in_version"] = version
                        cascaded += 1
                        break

    if cascaded:
        log.info("  Cascaded: %d related env vars / config options flagged", cascaded)
    return cascaded


def _cascade_recently_added(manifest, now):
    """Cascade recently_added from newly-added platforms/tools to their env vars/config.

    Parallel to _cascade_new_flags but for the same-version branch. Skips items that are
    already flagged (is_new or recently_added) so it's idempotent across runs.
    """
    ug = manifest.get("user_guide", {})
    tr = manifest.get("technical_reference", {})
    cascaded = 0

    new_platform_keys = {
        integ.get("key", "").lower()
        for integ in ug.get("integrations", [])
        if integ.get("recently_added") and integ.get("key")
    }
    new_tool_names = {
        tool.get("name", "").lower()
        for tool in ug.get("tools", [])
        if tool.get("recently_added") and tool.get("name")
    }

    if not (new_platform_keys or new_tool_names):
        return 0

    for ev in tr.get("environment_variables", []):
        if ev.get("is_new") or ev.get("recently_added"):
            continue
        name_lower = ev.get("name", "").lower()
        for pk in new_platform_keys:
            if name_lower.startswith(pk + "_"):
                ev["recently_added"] = True
                ev["added_at"] = now
                cascaded += 1
                break

    for opt in tr.get("config_options", []):
        if opt.get("is_new") or opt.get("recently_added"):
            continue
        key_lower = opt.get("key", "").lower()
        matched = False
        for tn in new_tool_names:
            if key_lower.startswith(f"auxiliary.{tn}."):
                opt["recently_added"] = True
                opt["added_at"] = now
                cascaded += 1
                matched = True
                break
        if matched:
            continue
        for pk in new_platform_keys:
            if key_lower.startswith(pk + "."):
                opt["recently_added"] = True
                opt["added_at"] = now
                cascaded += 1
                break

    return cascaded


def _detect_local_additions(manifest, previous, now):
    """Find items in current manifest not in snapshot — flag as recently_added.

    Skips entries in SELF_REFERENTIAL_ITEMS so Danual doesn't announce its own
    setup artifacts as user additions.
    """
    prev_names = _extract_item_names(previous)
    total = 0

    for items, key_field, section_key in _all_sections(manifest):
        old_names = prev_names.get(section_key, set())
        for item in items:
            item_key = item.get(key_field, "")
            if (section_key, item_key) in SELF_REFERENTIAL_ITEMS:
                continue
            if item_key not in old_names and not item.get("is_new") and not item.get("recently_added"):
                item["recently_added"] = True
                item["added_at"] = now
                total += 1

    return total


def _carry_forward_new_flags(manifest, previous):
    """Copy is_new/added_in_version from previous snapshot into current manifest."""
    prev_flags = _build_flag_lookup(previous, "is_new", "added_in_version")
    return _apply_flag_lookup(manifest, prev_flags, "is_new", "added_in_version")


def _carry_forward_recently_added(manifest, previous):
    """Copy recently_added/added_at from previous snapshot, expiring old ones."""
    days = _recently_added_days()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    prev_flags = {}

    for items, key_field, section_key in _all_sections(previous):
        for item in items:
            if not item.get("recently_added"):
                continue
            added_at = item.get("added_at", "")
            try:
                ts = datetime.fromisoformat(added_at.replace("Z", "+00:00"))
                if ts < cutoff:
                    continue
            except (ValueError, AttributeError):
                continue
            prev_flags[(section_key, item.get(key_field, ""))] = added_at

    total = 0
    for items, key_field, section_key in _all_sections(manifest):
        for item in items:
            key = (section_key, item.get(key_field, ""))
            if key in prev_flags:
                item["recently_added"] = True
                item["added_at"] = prev_flags[key]
                total += 1

    return total


def _build_flag_lookup(manifest, flag_field, value_field):
    """Build a {(section_key, item_key): value} lookup for flagged items."""
    lookup = {}
    for items, key_field, section_key in _all_sections(manifest):
        for item in items:
            if item.get(flag_field):
                lookup[(section_key, item.get(key_field, ""))] = item.get(value_field)
    return lookup


def _apply_flag_lookup(manifest, lookup, flag_field, value_field):
    """Apply a flag lookup to the manifest."""
    total = 0
    for items, key_field, section_key in _all_sections(manifest):
        for item in items:
            key = (section_key, item.get(key_field, ""))
            if key in lookup:
                item[flag_field] = True
                item[value_field] = lookup[key]
                total += 1
    return total


def _clear_all_flags(manifest):
    """Ensure all items have is_new=False and no recently_added."""
    for items, _, _ in _all_sections(manifest):
        for item in items:
            item["is_new"] = False
            item.pop("recently_added", None)
            item.pop("added_at", None)


def _unflag_self_items(manifest):
    """Strip recently_added from Danual's own setup artifacts (e.g., its own cron job).

    The manual shouldn't announce its own installation as a user addition.
    Run after carry-forward so any historically-flagged entries are cleaned up.
    """
    for items, key_field, section_key in _all_sections(manifest):
        for item in items:
            if (section_key, item.get(key_field, "")) in SELF_REFERENTIAL_ITEMS:
                item.pop("recently_added", None)
                item.pop("added_at", None)


def _save_snapshot(manifest):
    """Save a copy of the manifest as the diff baseline."""
    _atomic_write(SNAPSHOT_PATH, json.dumps(manifest, indent=2, ensure_ascii=False))
    log.info("Snapshot saved to %s", SNAPSHOT_PATH)


def main():
    log.info("═══ The Danual — Differ ═══")
    log.info("")
    manifest = diff_manifest()
    if manifest:
        new_count = 0
        recent_count = 0
        for items, _, _ in _all_sections(manifest):
            for item in items:
                if item.get("is_new"):
                    new_count += 1
                if item.get("recently_added"):
                    recent_count += 1
        log.info("")
        log.info("Done — %d version-new + %d recently-added items in manifest.json",
                 new_count, recent_count)


if __name__ == "__main__":
    main()
