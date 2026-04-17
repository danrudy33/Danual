#!/usr/bin/env bash
#
# The Danual — install
# Wires the hook and cron helper into the active Hermes layout, then runs
# the first build. Run once after `git clone`. Idempotent — safe to re-run.
#
# Usage:
#   bash scripts/install.sh            # interactive (asks before replacing files)
#   bash scripts/install.sh --yes      # non-interactive (replace without asking)
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"

ASSUME_YES=false
for arg in "$@"; do
    case "$arg" in
        --yes|-y) ASSUME_YES=true ;;
    esac
done

confirm() {
    $ASSUME_YES && return 0
    read -r -p "$1 [y/N] " reply
    [[ "$reply" =~ ^[Yy]$ ]]
}

echo ""
echo "📘 The Danual — install"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Repo:         $REPO_DIR"
echo "  Hermes home:  $HERMES_HOME"
echo ""

if [ ! -d "$HERMES_HOME" ]; then
    echo "✗ Hermes home not found at $HERMES_HOME"
    echo "  Install Hermes first: https://github.com/dealsinengines/hermes-agent"
    exit 1
fi

install_link() {
    local source="$1"
    local target="$2"
    local label="$3"

    if [ ! -e "$source" ]; then
        echo "✗ Source missing: $source"
        exit 1
    fi

    mkdir -p "$(dirname "$target")"

    if [ -L "$target" ] && [ "$(readlink "$target")" = "$source" ]; then
        echo "✓ $label already linked → $source"
        return 0
    fi

    if [ -e "$target" ] || [ -L "$target" ]; then
        echo "⚠  $target already exists."
        if ! confirm "   Replace with symlink to the repo?"; then
            echo "   Skipped — $label NOT installed. Auto-rebuild won't work until you re-run install.sh --yes."
            return 0
        fi
        rm -rf "$target"
    fi

    ln -s "$source" "$target"
    echo "✓ $label linked → $target"
}

# 1. Gateway startup hook
install_link \
    "$REPO_DIR/hooks/danual-rebuild" \
    "$HERMES_HOME/hooks/danual-rebuild" \
    "Gateway hook"

# 2. Nightly cron helper script (Hermes's cron system looks here for the script= field)
install_link \
    "$REPO_DIR/cron/danual_nightly.py" \
    "$HERMES_HOME/scripts/danual_nightly.py" \
    "Cron helper"

# 3. First build
echo ""
echo "▸ Running first build..."
bash "$SCRIPT_DIR/update_manual.sh"

# 4. Next steps
MANUAL="$HERMES_HOME/docs/Hermes_Manual.html"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✓ Install complete."
echo ""
echo "The gateway startup hook is active — the manual will rebuild after every"
echo "'hermes update' (or any gateway restart) automatically."
echo ""
echo "Open the manual:  file://$MANUAL"
echo ""
echo "Optional — nightly rebuild (catches local skills/MCP/cron you add"
echo "between Hermes updates). Register via Hermes's cron system:"
echo ""
echo "    hermes cron create   \\"
echo "        --name 'Danual Nightly Rebuild'   \\"
echo "        --script danual_nightly.py   \\"
echo "        --schedule '0 4 * * *'   \\"
echo "        --deliver '<your-telegram-or-discord-target>'"
echo ""
echo "Optional — one-word shell shortcut:"
echo "    bash $SCRIPT_DIR/install-alias.sh"
echo ""
