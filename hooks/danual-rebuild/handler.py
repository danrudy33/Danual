"""
The Danual — Post-startup rebuild hook.
Runs after gateway:startup (including after hermes update).
Only triggers a full rebuild if the Hermes version changed.
Always does a quick scan to catch user-added items (skills, MCP servers, etc).
"""

import json
import subprocess
import logging
from pathlib import Path

HERMES_HOME = Path.home() / ".hermes"
SCRIPT = HERMES_HOME / "skills" / "devops" / "danual" / "scripts" / "update_manual.sh"
MANIFEST = HERMES_HOME / "skills" / "devops" / "danual" / "output" / "manifest.json"
LOG_DIR = HERMES_HOME / "logs"
LOG_FILE = LOG_DIR / "danual-hook.log"

log = logging.getLogger("danual-hook")


def _current_hermes_version():
    agent_dir = HERMES_HOME / "hermes-agent"
    import re
    files = sorted(agent_dir.glob("RELEASE_v*.md"),
                   key=lambda f: [int(x) for x in re.findall(r"\d+", f.stem)])
    if files:
        m = re.search(r"v([\d.]+)", files[-1].stem)
        if m:
            return m.group(1)
    return None


def _manifest_version():
    if MANIFEST.exists():
        try:
            return json.loads(MANIFEST.read_text(encoding="utf-8")).get("version")
        except Exception:
            pass
    return None


async def handle(event_type: str, context: dict) -> None:
    if not SCRIPT.exists():
        return

    current = _current_hermes_version()
    manifest = _manifest_version()
    version_changed = current and manifest and current != manifest

    if version_changed:
        log.info("Danual: version changed (%s → %s), running full rebuild", manifest, current)
        cmd = ["bash", str(SCRIPT)]
    else:
        log.info("Danual: same version (%s), running quick rebuild (catches local additions)", current)
        cmd = ["bash", str(SCRIPT), "--no-enrich"]

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        # Open log file; Popen dups the fd for the child, so we can close the parent
        # handle via the `with` block after the subprocess is spawned.
        with open(LOG_FILE, "a", encoding="utf-8") as logfh:
            subprocess.Popen(cmd, stdout=logfh, stderr=subprocess.STDOUT, close_fds=True)
    except Exception as exc:
        log.error("Danual rebuild failed to start: %s", exc)
