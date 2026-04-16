#!/usr/bin/env python3
"""
The Danual — Differ (Phase 2)
Compares current manifest against previous snapshot, flags new items.

Two badge systems:
  - is_new (green ✨): Items new in a Hermes version update. Cleared on next version change.
  - recently_added (blue 🆕): User/local items detected between versions. Time-based (30 days).
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
OUTPUT_DIR = SCRIPT_DIR.parent / "output"
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"
SNAPSHOT_PATH = OUTPUT_DIR / ".manifest_snapshot.json"

RECENTLY_ADDED_DAYS = 30

logging.basicConfig(level=logging.INFO, format="  %(message)s")
log = logging.getLogger("danual-differ")


def _all_sections(manifest):
    """Yield (items_list, key_field) for every section in the manifest."""
    ug = manifest.get("user_guide", {})
    tr = manifest.get("technical_reference", {})
    yield ug.get("tools", []), "name"
    yield ug.get("commands", []), "name"
    yield ug.get("cli_subcommands", []), "name"
    yield ug.get("skills", {}).get("bundled", []), "name"
    yield ug.get("skills", {}).get("user_created", []), "name"
    yield ug.get("integrations", []), "key"
    yield tr.get("config_options", []), "key"
    yield tr.get("environment_variables", []), "name"
    yield tr.get("mcp_servers", []), "name"
    yield tr.get("cron_jobs", []), "name"
    yield tr.get("terminal_backends", []), "name"


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
        if item[key_field] in new_names:
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

    manifest = json.loads(MANIFEST_PATH.read_text())
    current_version = manifest.get("version", "unknown")
    is_first_run = not SNAPSHOT_PATH.exists()
    now = datetime.now(timezone.utc).isoformat()

    if is_first_run:
        log.info("First run — establishing baseline (nothing marked as new)")
        _clear_all_flags(manifest)
        _save_snapshot(manifest)
        MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
        return manifest

    previous = json.loads(SNAPSHOT_PATH.read_text())
    prev_version = previous.get("version", "unknown")

    if current_version == prev_version:
        log.info("Same version (%s) — preserving flags, checking for local additions", current_version)

        carried_new = _carry_forward_new_flags(manifest, previous)
        carried_recent = _carry_forward_recently_added(manifest, previous)
        local_added = _detect_local_additions(manifest, previous, now)
        manifest["previous_version"] = previous.get("previous_version")

        _save_snapshot(manifest)
        MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
        log.info("Carried forward %d version-new + %d recently-added flags, %d new local additions",
                 carried_new, carried_recent, local_added)
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
    for items, _ in _all_sections(manifest):
        for item in items:
            item.pop("recently_added", None)
            item.pop("added_at", None)

    log.info("")
    log.info("Total new items: %d (including %d cascaded)", total_new, cascade)

    _save_snapshot(manifest)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
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


def _detect_local_additions(manifest, previous, now):
    """Find items in current manifest not in snapshot — flag as recently_added."""
    prev_names = _extract_item_names(previous)
    curr_names = _extract_item_names(manifest)
    ug = manifest["user_guide"]
    tr = manifest["technical_reference"]
    total = 0

    section_map = [
        (ug.get("tools", []), "name", "tools"),
        (ug.get("commands", []), "name", "commands"),
        (ug.get("cli_subcommands", []), "name", "cli_subcommands"),
        (ug.get("skills", {}).get("bundled", []), "name", "skills_bundled"),
        (ug.get("skills", {}).get("user_created", []), "name", "skills_user"),
        (ug.get("integrations", []), "key", "integrations"),
        (tr.get("config_options", []), "key", "config_options"),
        (tr.get("environment_variables", []), "name", "environment_variables"),
        (tr.get("mcp_servers", []), "name", "mcp_servers"),
        (tr.get("cron_jobs", []), "name", "cron_jobs"),
        (tr.get("terminal_backends", []), "name", "terminal_backends"),
    ]

    for items, key_field, section_key in section_map:
        old_names = prev_names.get(section_key, set())
        for item in items:
            item_key = item.get(key_field, "")
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
    cutoff = datetime.now(timezone.utc) - timedelta(days=RECENTLY_ADDED_DAYS)
    prev_flags = {}

    for items, key_field in _all_sections(previous):
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
            section_prefix = _section_prefix(items, previous)
            prev_flags[(section_prefix, item.get(key_field, ""))] = added_at

    ug = manifest["user_guide"]
    tr = manifest["technical_reference"]
    total = 0

    for items, key_field in _all_sections(manifest):
        sp = _section_prefix(items, manifest)
        for item in items:
            key = (sp, item.get(key_field, ""))
            if key in prev_flags:
                item["recently_added"] = True
                item["added_at"] = prev_flags[key]
                total += 1

    return total


def _build_flag_lookup(manifest, flag_field, value_field):
    """Build a {(section_prefix, item_key): value} lookup for flagged items."""
    lookup = {}
    for items, key_field in _all_sections(manifest):
        sp = _section_prefix(items, manifest)
        for item in items:
            if item.get(flag_field):
                lookup[(sp, item.get(key_field, ""))] = item.get(value_field)
    return lookup


def _apply_flag_lookup(manifest, lookup, flag_field, value_field):
    """Apply a flag lookup to the manifest."""
    total = 0
    for items, key_field in _all_sections(manifest):
        sp = _section_prefix(items, manifest)
        for item in items:
            key = (sp, item.get(key_field, ""))
            if key in lookup:
                item[flag_field] = True
                item[value_field] = lookup[key]
                total += 1
    return total


def _section_prefix(items, manifest):
    """Determine a unique prefix for a section based on its identity in the manifest."""
    ug = manifest.get("user_guide", {})
    tr = manifest.get("technical_reference", {})
    id_map = {
        id(ug.get("tools", [])): "tool",
        id(ug.get("commands", [])): "cmd",
        id(ug.get("cli_subcommands", [])): "cli",
        id(ug.get("skills", {}).get("bundled", [])): "skill_b",
        id(ug.get("skills", {}).get("user_created", [])): "skill_u",
        id(ug.get("integrations", [])): "integ",
        id(tr.get("config_options", [])): "cfg",
        id(tr.get("environment_variables", [])): "env",
        id(tr.get("mcp_servers", [])): "mcp",
        id(tr.get("cron_jobs", [])): "cron",
        id(tr.get("terminal_backends", [])): "be",
    }
    return id_map.get(id(items), "unknown")


def _clear_all_flags(manifest):
    """Ensure all items have is_new=False and no recently_added."""
    for items, _ in _all_sections(manifest):
        for item in items:
            item["is_new"] = False
            item.pop("recently_added", None)
            item.pop("added_at", None)


def _save_snapshot(manifest):
    """Save a copy of the manifest as the diff baseline."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    log.info("Snapshot saved to %s", SNAPSHOT_PATH)


def main():
    log.info("═══ The Danual — Differ ═══")
    log.info("")
    manifest = diff_manifest()
    if manifest:
        new_count = 0
        recent_count = 0
        for items, _ in _all_sections(manifest):
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
