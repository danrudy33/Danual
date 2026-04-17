#!/usr/bin/env python3
"""
The Danual — Scanner (Phase 1)
Extracts all feature data from the Hermes installation into manifest.json.

Must be run with the Hermes venv Python:
    ~/.hermes/hermes-agent/venv/bin/python3 regenerate_manual.py
"""

import sys
import os
import json
import re
import importlib
import logging
from pathlib import Path
from datetime import datetime, timezone

HERMES_HOME = Path.home() / ".hermes"
HERMES_AGENT = HERMES_HOME / "hermes-agent"
SKILLS_DIR = HERMES_HOME / "skills"
CONFIG_PATH = HERMES_HOME / "config.yaml"
SCRIPT_DIR = Path(__file__).parent
OUTPUT_DIR = SCRIPT_DIR.parent / "output"
DOCS_DIR = HERMES_HOME / "docs"

logging.basicConfig(level=logging.INFO, format="  %(message)s")
log = logging.getLogger("danual-scanner")


def _atomic_write(path: Path, content: str) -> None:
    """Write via temp-file + os.replace so concurrent readers never see a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def _version_sort_key(s: str):
    """Tolerant semver sort key — extracts integer parts, ignores suffixes like '-rc1'."""
    parts = []
    for seg in s.split("."):
        m = re.match(r"(\d+)", seg)
        parts.append(int(m.group(1)) if m else 0)
    return parts


def _setup_hermes_imports():
    """Add hermes-agent to sys.path for direct imports."""
    agent_str = str(HERMES_AGENT)
    if agent_str not in sys.path:
        sys.path.insert(0, agent_str)
    os.chdir(HERMES_AGENT)


# ─── Tools ────────────────────────────────────────────────────────────────────

def scan_tools():
    """Extract all registered tools from the Hermes tool registry."""
    _setup_hermes_imports()
    tools = []

    try:
        from tools.registry import registry

        tools_dir = HERMES_AGENT / "tools"
        for f in sorted(tools_dir.glob("*.py")):
            if f.name.startswith("_"):
                continue
            module_name = f"tools.{f.stem}"
            try:
                importlib.import_module(module_name)
            except Exception as exc:
                log.warning("Could not import %s: %s", module_name, exc)

        for entry in registry._snapshot_entries():
            schema = entry.schema or {}
            params = schema.get("parameters", {})
            props = params.get("properties", {})
            tools.append({
                "name": entry.name,
                "description": (schema.get("description", "") or entry.description or "").strip(),
                "category": entry.toolset,
                "source": "hermes" if not entry.toolset.startswith("mcp-") else "mcp",
                "is_new": False,
                "added_in_version": None,
                "usage": "",
                "parameters": list(props.keys()),
                "explainer": {"what_it_does": "", "why_it_matters": "", "example_use_case": ""},
            })
        if not tools:
            log.warning("Tools: registry returned 0 entries — registry._snapshot_entries() may have changed")
        else:
            log.info("Tools: %d found via registry import", len(tools))

    except Exception as exc:
        log.error("Registry import failed (%s), falling back to static scan", exc)
        tools = _scan_tools_static()

    return sorted(tools, key=lambda t: t["name"])


def _scan_tools_static():
    """Fallback: extract tool registrations via regex on source files."""
    tools = []
    tools_dir = HERMES_AGENT / "tools"
    pattern = re.compile(
        r'registry\.register\(\s*'
        r'name\s*=\s*["\']([^"\']+)["\'].*?'
        r'toolset\s*=\s*["\']([^"\']+)["\']',
        re.DOTALL,
    )
    desc_in_schema = re.compile(r'"description"\s*:\s*"([^"]{5,200})"')

    for f in sorted(tools_dir.glob("*.py")):
        if f.name.startswith("_"):
            continue
        content = f.read_text(encoding="utf-8", errors="replace")
        for m in pattern.finditer(content):
            name, toolset = m.group(1), m.group(2)
            desc = ""
            schema_var_match = re.search(
                rf'name\s*=\s*["\']{ re.escape(name) }["\'].*?schema\s*=\s*(\w+)',
                content, re.DOTALL,
            )
            if schema_var_match:
                var_name = schema_var_match.group(1)
                var_block = re.search(
                    rf'{var_name}\s*=\s*\{{(.+?)\}}', content, re.DOTALL
                )
                if var_block:
                    dm = desc_in_schema.search(var_block.group(1))
                    if dm:
                        desc = dm.group(1)
            tools.append({
                "name": name,
                "description": desc,
                "category": toolset,
                "source": "hermes",
                "is_new": False,
                "added_in_version": None,
                "usage": "",
                "parameters": [],
                "explainer": {"what_it_does": "", "why_it_matters": "", "example_use_case": ""},
            })
    log.info("Tools: %d found via static scan", len(tools))
    return tools


# ─── Commands ─────────────────────────────────────────────────────────────────

def scan_commands():
    """Extract all slash commands from COMMAND_REGISTRY."""
    _setup_hermes_imports()
    commands = []

    try:
        from hermes_cli.commands import COMMAND_REGISTRY

        for cmd in COMMAND_REGISTRY:
            if cmd.cli_only:
                context = "cli"
            elif cmd.gateway_only:
                context = "gateway"
            else:
                context = "both"

            commands.append({
                "name": f"/{cmd.name}",
                "description": cmd.description,
                "category": cmd.category,
                "context": context,
                "aliases": [f"/{a}" for a in cmd.aliases],
                "args_hint": cmd.args_hint,
                "subcommands": list(cmd.subcommands),
                "source": "hermes",
                "is_new": False,
                "added_in_version": None,
                "usage": f"/{cmd.name} {cmd.args_hint}".strip(),
                "explainer": {"what_it_does": "", "why_it_matters": "", "example_use_case": ""},
            })
        log.info("Commands: %d found", len(commands))

    except Exception as exc:
        log.error("Command registry import failed: %s", exc)

    return commands


# ─── CLI Subcommands ──────────────────────────────────────────────────────────

def scan_cli_subcommands():
    """Extract CLI subcommands from argparse definitions in main.py."""
    main_py = HERMES_AGENT / "hermes_cli" / "main.py"
    if not main_py.exists():
        log.warning("main.py not found")
        return []

    content = main_py.read_text(encoding="utf-8", errors="replace")
    subcommands = []
    seen = set()

    pattern = re.compile(
        r'subparsers\.add_parser\(\s*["\'](\w[\w-]*)["\']'
        r'.*?help\s*=\s*["\'](.+?)["\']',
        re.DOTALL,
    )

    for m in pattern.finditer(content):
        name = m.group(1)
        desc = m.group(2)
        if name in seen:
            continue
        seen.add(name)
        subcommands.append({
            "name": f"hermes {name}",
            "description": desc,
            "context": "cli",
            "source": "hermes",
            "is_new": False,
            "added_in_version": None,
            "explainer": {"what_it_does": "", "why_it_matters": "", "example_use_case": ""},
        })

    if not subcommands:
        log.warning("CLI subcommands: 0 found — argparse pattern may have changed in main.py")
    else:
        log.info("CLI subcommands: %d found", len(subcommands))
    return subcommands


# ─── Skills ───────────────────────────────────────────────────────────────────

def scan_skills():
    """Scan skills, separating bundled from user-created."""
    bundled_names = set()
    manifest_path = SKILLS_DIR / ".bundled_manifest"
    if manifest_path.exists():
        for line in manifest_path.read_text().splitlines():
            line = line.strip()
            if ":" in line:
                bundled_names.add(line.split(":")[0])

    bundled = []
    user_created = []

    for skill_md in sorted(SKILLS_DIR.rglob("SKILL.md")):
        meta = _parse_skill_md(skill_md)
        if not meta.get("name"):
            continue

        is_bundled = meta["name"] in bundled_names
        entry = {
            "name": meta["name"],
            "description": meta.get("description", ""),
            "source": "hermes" if is_bundled else "user",
            "is_new": False,
            "added_in_version": None,
            "version": meta.get("version", ""),
            "explainer": {"what_it_does": "", "why_it_matters": "", "example_use_case": ""},
        }
        if is_bundled:
            bundled.append(entry)
        else:
            user_created.append(entry)

    log.info("Skills: %d bundled, %d user-created", len(bundled), len(user_created))
    return {"bundled": bundled, "user_created": user_created}


def _parse_skill_md(path):
    """Parse YAML frontmatter from a SKILL.md file."""
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.startswith("---"):
        return {"name": path.parent.name}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {"name": path.parent.name}
    try:
        import yaml
        meta = yaml.safe_load(parts[1]) or {}
    except Exception:
        meta = {}
    if "name" not in meta:
        meta["name"] = path.parent.name
    return meta


# ─── Platform Integrations ────────────────────────────────────────────────────

def scan_integrations():
    """Extract platform integrations from the platforms registry."""
    _setup_hermes_imports()
    integrations = []

    try:
        from hermes_cli.platforms import PLATFORMS

        for key, info in PLATFORMS.items():
            integrations.append({
                "name": info.label.strip(),
                "key": key,
                "description": f"Platform adapter for {info.label.strip()}",
                "default_toolset": info.default_toolset,
                "source": "hermes",
                "is_new": False,
                "added_in_version": None,
                "explainer": {"what_it_does": "", "why_it_matters": "", "example_use_case": ""},
            })
        log.info("Integrations: %d platforms found", len(integrations))

    except Exception as exc:
        log.error("Platforms import failed: %s", exc)

    return integrations


# ─── MCP Servers ──────────────────────────────────────────────────────────────

def scan_mcp_servers():
    """Read MCP server registrations from config.yaml."""
    servers = []
    try:
        import yaml
        config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
        mcp = config.get("mcp_servers", {}) or {}
        for name, cfg in mcp.items():
            servers.append({
                "name": name,
                "description": f"MCP server: {name}",
                "command": cfg.get("command", ""),
                "args": cfg.get("args", []),
                "source": "user",
                "is_new": False,
                "added_in_version": None,
                "explainer": {"what_it_does": "", "why_it_matters": "", "example_use_case": ""},
            })
        log.info("MCP Servers: %d found", len(servers))
    except Exception as exc:
        log.error("MCP scan failed: %s", exc)
    return servers


# ─── Config Options ───────────────────────────────────────────────────────────

def scan_config_options():
    """Extract config options from DEFAULT_CONFIG."""
    _setup_hermes_imports()
    options = []

    try:
        from hermes_cli.config import DEFAULT_CONFIG
        _flatten_config(DEFAULT_CONFIG, "", options)
        log.info("Config options: %d found", len(options))
    except Exception as exc:
        log.error("Config scan failed: %s", exc)

    return options


def _flatten_config(d, prefix, result):
    """Recursively flatten a nested config dict into dotpath entries."""
    for key, value in d.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict) and value:
            _flatten_config(value, full_key, result)
        else:
            result.append({
                "key": full_key,
                "description": "",
                "default_value": _json_safe(value),
                "source": "hermes",
                "is_new": False,
                "explainer": {"what_it_does": "", "why_it_matters": "", "example_use_case": ""},
            })


def _json_safe(val):
    """Make a value JSON-serializable."""
    if isinstance(val, (str, int, float, bool, type(None))):
        return val
    return str(val)


# ─── Environment Variables ────────────────────────────────────────────────────

def scan_env_vars():
    """Extract environment variables from OPTIONAL_ENV_VARS and .env.example."""
    _setup_hermes_imports()
    env_vars = []
    seen = set()

    try:
        from hermes_cli.config import OPTIONAL_ENV_VARS
        for var_name, info in OPTIONAL_ENV_VARS.items():
            env_vars.append({
                "name": var_name,
                "description": info.get("description", ""),
                "source": "hermes",
                "is_new": False,
                "explainer": {"what_it_does": "", "why_it_matters": "", "example_use_case": ""},
            })
            seen.add(var_name)
        log.info("Env vars: %d from OPTIONAL_ENV_VARS", len(env_vars))
    except Exception as exc:
        log.warning("OPTIONAL_ENV_VARS import failed: %s", exc)

    env_example = HERMES_AGENT / ".env.example"
    if env_example.exists():
        pattern = re.compile(r"^#?\s*([A-Z][A-Z0-9_]+)\s*=", re.MULTILINE)
        content = env_example.read_text(encoding="utf-8", errors="replace")
        extra = 0
        for m in pattern.finditer(content):
            name = m.group(1)
            if name not in seen:
                desc_match = re.search(
                    rf"#\s*(.+)\n.*{re.escape(name)}\s*=",
                    content[max(0, m.start() - 200):m.end()],
                )
                env_vars.append({
                    "name": name,
                    "description": desc_match.group(1).strip() if desc_match else "",
                    "source": "hermes",
                    "is_new": False,
                    "explainer": {"what_it_does": "", "why_it_matters": "", "example_use_case": ""},
                })
                seen.add(name)
                extra += 1
        if extra:
            log.info("Env vars: %d additional from .env.example", extra)

    env_doc = HERMES_AGENT / "website" / "docs" / "reference" / "environment-variables.md"
    if env_doc.exists():
        pattern = re.compile(r"\|\s*`([A-Z][A-Z0-9_]+)`\s*\|\s*(.+?)\s*\|")
        content = env_doc.read_text(encoding="utf-8", errors="replace")
        extra = 0
        for m in pattern.finditer(content):
            name, desc = m.group(1), m.group(2).strip()
            if name not in seen:
                env_vars.append({
                    "name": name,
                    "description": desc,
                    "source": "hermes",
                    "is_new": False,
                    "explainer": {"what_it_does": "", "why_it_matters": "", "example_use_case": ""},
                })
                seen.add(name)
                extra += 1
            else:
                for ev in env_vars:
                    if ev["name"] == name and not ev["description"] and desc:
                        ev["description"] = desc
                        break
        if extra:
            log.info("Env vars: %d additional from docs", extra)

    return sorted(env_vars, key=lambda e: e["name"])


# ─── Cron Jobs ────────────────────────────────────────────────────────────────

def scan_cron_jobs():
    """Read configured cron jobs from the cron system."""
    jobs = []
    jobs_file = HERMES_HOME / "cron" / "jobs.json"
    if not jobs_file.exists():
        log.info("Cron: no jobs.json found")
        return jobs

    try:
        data = json.loads(jobs_file.read_text(encoding="utf-8"))
        for job in data.get("jobs", []):
            jobs.append({
                "name": job.get("name", job.get("id", "unknown")),
                "id": job.get("id", ""),
                "description": (job.get("prompt", "")[:120] + "...") if len(job.get("prompt", "")) > 120 else job.get("prompt", ""),
                "schedule": job.get("schedule_display", job.get("schedule", {}).get("display", "")),
                "enabled": job.get("enabled", True),
                "deliver": job.get("deliver", ""),
                "source": "user",
                "is_new": False,
                "explainer": {"what_it_does": "", "why_it_matters": "", "example_use_case": ""},
            })
        log.info("Cron jobs: %d found", len(jobs))
    except Exception as exc:
        log.error("Cron scan failed: %s", exc)

    return jobs


# ─── Terminal Backends ────────────────────────────────────────────────────────

def scan_terminal_backends():
    """Extract supported terminal backends."""
    _SKIP = {"base", "file_sync", "modal_utils", "managed_modal", "__init__"}
    backends = {
        "local": "Local shell execution — runs commands directly on the host machine",
        "docker": "Docker container execution — isolated environment with configurable images",
        "ssh": "Remote execution via SSH — run commands on remote servers",
        "modal": "Modal serverless GPU execution — cloud compute with GPU support",
        "daytona": "Daytona cloud workspace execution — managed dev environments",
        "singularity": "Singularity/Apptainer container execution — HPC-friendly containers",
    }
    env_dir = HERMES_AGENT / "tools" / "environments"
    if env_dir.exists():
        for f in sorted(env_dir.glob("*.py")):
            name = f.stem
            if name.startswith("_") or name in _SKIP:
                continue
            if name not in backends:
                backends[name] = f"Terminal backend: {name}"
    result = []
    for name, desc in backends.items():
        result.append({
            "name": name,
            "description": desc,
            "source": "hermes",
        })
    for b in result:
        b.setdefault("is_new", False)
        b.setdefault("explainer", {"what_it_does": "", "why_it_matters": "", "example_use_case": ""})
    log.info("Terminal backends: %d found", len(result))
    return result


# ─── Release Notes ────────────────────────────────────────────────────────────

def scan_release_notes():
    """Parse RELEASE_v*.md files for version metadata, highlights, and all sections."""
    releases = []
    pattern = re.compile(r"RELEASE_v([\d.]+)\.md$")

    for f in sorted(HERMES_AGENT.glob("RELEASE_v*.md")):
        m = pattern.search(f.name)
        if not m:
            continue
        version = m.group(1)
        content = f.read_text(encoding="utf-8", errors="replace")

        header_match = re.search(r"#\s*Hermes Agent v[\d.]+\s*\(v([\d.]+)\)", content)
        date_match = re.search(r"\*\*Release Date:\*\*\s*(.+)", content)
        stats_match = re.search(r"\*\*Since v[\d.]+:\*\*\s*(.+)", content)

        highlights = []
        sections = []
        current_section = None

        for line in content.splitlines():
            h2 = re.match(r"##\s+(.+)", line)
            h3 = re.match(r"###\s+(.+)", line)
            bullet = re.match(r"-\s+\*\*(.+?)\*\*\s*[—–-]\s*(.+?)(?:\s*\(\[#|$)", line)
            bullet_simple = re.match(r"-\s+\*\*(.+?)\*\*\s*(.+?)(?:\s*\(\[#|$)", line)

            if h2:
                title = h2.group(1).strip()
                title_clean = re.sub(r"[^\w\s&]", "", title).strip()
                if current_section:
                    sections.append(current_section)
                current_section = {"title": title_clean, "items": []}
                continue

            if h3 and current_section:
                current_section["items"].append({"subtitle": h3.group(1).strip()})
                continue

            if bullet:
                entry = {"title": bullet.group(1).strip(), "summary": bullet.group(2).strip()}
                if current_section is not None:
                    current_section["items"].append(entry)
                    if "Highlights" in (current_section.get("title") or ""):
                        highlights.append(entry)
                continue

            if bullet_simple and current_section is not None:
                entry = {"title": bullet_simple.group(1).strip(), "summary": bullet_simple.group(2).strip()}
                current_section["items"].append(entry)
                if "Highlights" in (current_section.get("title") or ""):
                    highlights.append(entry)

        if current_section:
            sections.append(current_section)

        releases.append({
            "version": version,
            "tag": header_match.group(1) if header_match else "",
            "date": date_match.group(1).strip() if date_match else "",
            "stats": stats_match.group(1).strip() if stats_match else "",
            "highlights": highlights,
            "sections": sections,
        })

    releases.sort(key=lambda r: _version_sort_key(r["version"]), reverse=True)
    log.info("Release notes: %d versions parsed", len(releases))
    return releases


# ─── Version ──────────────────────────────────────────────────────────────────

def get_current_version():
    """Determine the current Hermes version."""
    import subprocess

    release_files = sorted(
        HERMES_AGENT.glob("RELEASE_v*.md"),
        key=lambda f: _version_sort_key("".join(re.findall(r"\d+|\.", f.stem))),
    )
    semver = "0.0.0"
    if release_files:
        m = re.search(r"v([\d.]+)", release_files[-1].stem)
        if m:
            semver = m.group(1)

    try:
        tag = subprocess.check_output(
            ["git", "describe", "--tags"],
            cwd=HERMES_AGENT, stderr=subprocess.DEVNULL, text=True,
        ).strip()
    except Exception:
        tag = ""

    return semver, tag


# ─── Assemble ─────────────────────────────────────────────────────────────────

def build_manifest():
    """Run all scanners and assemble the manifest."""
    log.info("═══ The Danual — Scanner ═══")
    log.info("")

    version, git_tag = get_current_version()
    log.info("Hermes version: %s (%s)", version, git_tag)
    log.info("")

    log.info("Scanning tools...")
    tools = scan_tools()

    log.info("Scanning commands...")
    commands = scan_commands()

    log.info("Scanning CLI subcommands...")
    cli_subcommands = scan_cli_subcommands()

    log.info("Scanning skills...")
    skills = scan_skills()

    log.info("Scanning integrations...")
    integrations = scan_integrations()

    log.info("Scanning MCP servers...")
    mcp_servers = scan_mcp_servers()

    log.info("Scanning config options...")
    config_options = scan_config_options()

    log.info("Scanning environment variables...")
    env_vars = scan_env_vars()

    log.info("Scanning cron jobs...")
    cron_jobs = scan_cron_jobs()

    log.info("Scanning terminal backends...")
    terminal_backends = scan_terminal_backends()

    log.info("Parsing release notes...")
    release_notes = scan_release_notes()

    manifest = {
        "platform": "hermes",
        "version": version,
        "git_tag": git_tag,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "previous_version": None,

        "user_guide": {
            "tools": tools,
            "commands": commands,
            "cli_subcommands": cli_subcommands,
            "skills": skills,
            "integrations": integrations,
        },

        "technical_reference": {
            "config_options": config_options,
            "environment_variables": env_vars,
            "mcp_servers": mcp_servers,
            "cron_jobs": cron_jobs,
            "terminal_backends": terminal_backends,
        },

        "release_notes": release_notes,

        "section_intros": {
            "tools": "",
            "commands": "",
            "cli_subcommands": "",
            "skills": "",
            "integrations": "",
            "config_options": "",
            "environment_variables": "",
            "mcp_servers": "",
            "cron_jobs": "",
            "terminal_backends": "",
        },
    }

    return manifest


def _merge_existing_enrichment(manifest):
    """Preserve explainers, section intros, and flags from a previously written manifest."""
    existing_path = OUTPUT_DIR / "manifest.json"
    if not existing_path.exists():
        return
    try:
        existing = json.loads(existing_path.read_text(encoding="utf-8"))
    except Exception:
        return

    old_intros = existing.get("section_intros", {})
    for key, val in old_intros.items():
        if val and not manifest["section_intros"].get(key):
            manifest["section_intros"][key] = val

    def _build_lookup(items, key_field="name"):
        """Build lookup of item-key → (explainer, flag-fields) from old items."""
        return {
            item.get(key_field, ""): item
            for item in items
            if item.get(key_field)
        }

    old_ug = existing.get("user_guide", {})
    old_tr = existing.get("technical_reference", {})

    lookups = {
        ("tools", "name"): _build_lookup(old_ug.get("tools", [])),
        ("commands", "name"): _build_lookup(old_ug.get("commands", [])),
        ("cli_subcommands", "name"): _build_lookup(old_ug.get("cli_subcommands", [])),
        ("skills_bundled", "name"): _build_lookup(old_ug.get("skills", {}).get("bundled", [])),
        ("skills_user", "name"): _build_lookup(old_ug.get("skills", {}).get("user_created", [])),
        ("integrations", "name"): _build_lookup(old_ug.get("integrations", [])),
        ("config_options", "key"): _build_lookup(old_tr.get("config_options", []), "key"),
        ("env_vars", "name"): _build_lookup(old_tr.get("environment_variables", [])),
        ("mcp_servers", "name"): _build_lookup(old_tr.get("mcp_servers", [])),
        ("cron_jobs", "name"): _build_lookup(old_tr.get("cron_jobs", [])),
        ("terminal_backends", "name"): _build_lookup(old_tr.get("terminal_backends", [])),
    }

    ug = manifest["user_guide"]
    tr = manifest["technical_reference"]

    sections = [
        (ug.get("tools", []), "tools", "name"),
        (ug.get("commands", []), "commands", "name"),
        (ug.get("cli_subcommands", []), "cli_subcommands", "name"),
        (ug.get("skills", {}).get("bundled", []), "skills_bundled", "name"),
        (ug.get("skills", {}).get("user_created", []), "skills_user", "name"),
        (ug.get("integrations", []), "integrations", "name"),
        (tr.get("config_options", []), "config_options", "key"),
        (tr.get("environment_variables", []), "env_vars", "name"),
        (tr.get("mcp_servers", []), "mcp_servers", "name"),
        (tr.get("cron_jobs", []), "cron_jobs", "name"),
        (tr.get("terminal_backends", []), "terminal_backends", "name"),
    ]
    merged_exp = 0
    merged_flags = 0
    for items, section_key, key_field in sections:
        lk = lookups.get((section_key, key_field), {})
        for item in items:
            old_item = lk.get(item.get(key_field, ""))
            if not old_item:
                continue
            old_exp = old_item.get("explainer", {})
            if old_exp.get("what_it_does") and not item.get("explainer", {}).get("what_it_does"):
                item["explainer"] = old_exp
                merged_exp += 1
            if old_item.get("is_new") and not item.get("is_new"):
                item["is_new"] = True
                if old_item.get("added_in_version"):
                    item["added_in_version"] = old_item["added_in_version"]
                merged_flags += 1
            if old_item.get("recently_added") and not item.get("recently_added"):
                item["recently_added"] = True
                if old_item.get("added_at"):
                    item["added_at"] = old_item["added_at"]
                merged_flags += 1
    if merged_exp or merged_flags:
        log.info("Merged %d cached explainers and %d flags from previous manifest",
                 merged_exp, merged_flags)


def main():
    manifest = build_manifest()
    _merge_existing_enrichment(manifest)

    output_path = OUTPUT_DIR / "manifest.json"
    _atomic_write(output_path, json.dumps(manifest, indent=2, ensure_ascii=False))

    summary = (
        f"\n  ══════════════════════════════════════\n"
        f"  Manifest written to {output_path}\n"
        f"  Version: {manifest['version']}\n"
        f"  Tools: {len(manifest['user_guide']['tools'])}\n"
        f"  Commands: {len(manifest['user_guide']['commands'])}\n"
        f"  CLI subcommands: {len(manifest['user_guide']['cli_subcommands'])}\n"
        f"  Skills: {len(manifest['user_guide']['skills']['bundled'])} bundled, "
        f"{len(manifest['user_guide']['skills']['user_created'])} user\n"
        f"  Integrations: {len(manifest['user_guide']['integrations'])}\n"
        f"  Config options: {len(manifest['technical_reference']['config_options'])}\n"
        f"  Env vars: {len(manifest['technical_reference']['environment_variables'])}\n"
        f"  MCP servers: {len(manifest['technical_reference']['mcp_servers'])}\n"
        f"  Cron jobs: {len(manifest['technical_reference']['cron_jobs'])}\n"
        f"  Terminal backends: {len(manifest['technical_reference']['terminal_backends'])}\n"
        f"  Release notes: {len(manifest['release_notes'])} versions\n"
        f"  ══════════════════════════════════════\n"
    )
    print(summary)


if __name__ == "__main__":
    main()
