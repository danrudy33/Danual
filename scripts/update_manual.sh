#!/usr/bin/env bash
#
# The Danual — Update Manual (Phase 5 Wrapper)
# Orchestrates: scanner → differ → enricher → renderer → notification
#
# Usage:
#   ./update_manual.sh              # Full pipeline
#   ./update_manual.sh --no-enrich  # Skip LLM enrichment (use cached)
#   ./update_manual.sh --scan-only  # Only run the scanner
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
HERMES_AGENT="$HERMES_HOME/hermes-agent"
VENV_PYTHON="$HERMES_AGENT/venv/bin/python3"
SYSTEM_PYTHON="$(command -v python3)"
OUTPUT_DIR="$SCRIPT_DIR/../output"
MANIFEST="$OUTPUT_DIR/manifest.json"
MANUAL="$HERMES_HOME/docs/Hermes_Manual.html"
LOCKDIR="$OUTPUT_DIR/.rebuild.lock"

# Portable advisory lock: mkdir is atomic on POSIX filesystems.
# If another rebuild is in progress, exit quietly — both scheduled rebuilds are
# fire-and-forget, so skipping is safer than racing the shared manifest file.
mkdir -p "$OUTPUT_DIR"
if ! mkdir "$LOCKDIR" 2>/dev/null; then
    # Stale lock? Remove if older than 10 min (pipeline is ~5s, so anything older is orphaned).
    if find "$LOCKDIR" -maxdepth 0 -mmin +10 2>/dev/null | grep -q .; then
        rmdir "$LOCKDIR" 2>/dev/null || true
        mkdir "$LOCKDIR" 2>/dev/null || { echo "⚠  Another rebuild is in progress, exiting."; exit 0; }
    else
        echo "⚠  Another rebuild is in progress, exiting."
        exit 0
    fi
fi
trap 'rmdir "$LOCKDIR" 2>/dev/null || true' EXIT INT TERM

# Use venv Python for scanner (needs hermes imports), system Python for the rest
SCANNER_PYTHON="$VENV_PYTHON"
if [ ! -f "$SCANNER_PYTHON" ]; then
    echo "⚠  Hermes venv Python not found at $VENV_PYTHON"
    echo "   Falling back to system Python (static scan only)"
    SCANNER_PYTHON="$SYSTEM_PYTHON"
fi
OTHER_PYTHON="$SYSTEM_PYTHON"

NO_ENRICH=false
SCAN_ONLY=false
for arg in "$@"; do
    case "$arg" in
        --no-enrich) NO_ENRICH=true ;;
        --scan-only) SCAN_ONLY=true ;;
    esac
done

echo ""
echo "📘 The Danual — Updating Manual"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Step 1: Scanner
echo "▸ Phase 1: Scanning Hermes installation..."
"$SCANNER_PYTHON" "$SCRIPT_DIR/regenerate_manual.py"

if $SCAN_ONLY; then
    echo ""
    echo "✓ Scan complete. Manifest at: $MANIFEST"
    exit 0
fi

# Step 2: Differ
echo ""
echo "▸ Phase 2: Diffing against previous snapshot..."
"$OTHER_PYTHON" "$SCRIPT_DIR/diff_manifest.py"

# Step 3: Enricher (unless --no-enrich)
if ! $NO_ENRICH; then
    echo ""
    echo "▸ Phase 3: Enriching with descriptions..."
    "$OTHER_PYTHON" "$SCRIPT_DIR/enrich_manifest.py"
fi

# Step 4: Renderer
echo ""
echo "▸ Phase 4: Rendering HTML manual..."
"$OTHER_PYTHON" "$SCRIPT_DIR/render_manual.py"

# Step 5: Notification summary
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

VERSION=$("$OTHER_PYTHON" -c "import json; print(json.load(open('$MANIFEST'))['version'])" 2>/dev/null || echo "?")
COUNTS=$("$OTHER_PYTHON" "$SCRIPT_DIR/_count_flags.py" 2>/dev/null || echo "0 0")
NEW_COUNT=$(echo "$COUNTS" | cut -d' ' -f1)
RECENT_COUNT=$(echo "$COUNTS" | cut -d' ' -f2)

MSG="📘 The Danual updated for v$VERSION"
if [ "$NEW_COUNT" -gt 0 ] 2>/dev/null && [ "$RECENT_COUNT" -gt 0 ] 2>/dev/null; then
    MSG="$MSG — $NEW_COUNT new in v$VERSION + $RECENT_COUNT recent user additions"
elif [ "$NEW_COUNT" -gt 0 ] 2>/dev/null; then
    MSG="$MSG — $NEW_COUNT new items highlighted"
elif [ "$RECENT_COUNT" -gt 0 ] 2>/dev/null; then
    MSG="$MSG — $RECENT_COUNT recent user additions"
fi
echo "$MSG"
echo "   View: file://$MANUAL"

# Tip: suggest the 'danual' alias if it's not already set in a common rc file
HAS_ALIAS=false
for RC in "$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.bash_profile"; do
    if [ -f "$RC" ] && grep -q "alias danual=" "$RC" 2>/dev/null; then
        HAS_ALIAS=true
        break
    fi
done
if ! $HAS_ALIAS; then
    echo "   Tip: run '$SCRIPT_DIR/install-alias.sh' to add a 'danual' shortcut"
fi
echo ""
