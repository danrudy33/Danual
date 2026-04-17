#!/usr/bin/env bash
#
# The Danual — Optional shell alias installer
# Adds a 'danual' alias to your shell rc file so you can open the manual
# with one word. Opt-in; asks before modifying anything.
#

set -euo pipefail

MANUAL_PATH="$HOME/.hermes/docs/Danual.html"

# Pick platform-appropriate opener
if [[ "$(uname)" == "Darwin" ]]; then
    OPENER="open"
else
    OPENER="xdg-open"
fi

ALIAS_LINE="alias danual='$OPENER \"$MANUAL_PATH\"'"

# Pick rc file from $SHELL
case "${SHELL:-}" in
    */zsh)
        RC="$HOME/.zshrc"
        ;;
    */bash)
        if [[ "$(uname)" == "Darwin" && -f "$HOME/.bash_profile" ]]; then
            RC="$HOME/.bash_profile"
        else
            RC="$HOME/.bashrc"
        fi
        ;;
    *)
        RC="$HOME/.zshrc"
        ;;
esac

echo ""
echo "📘 The Danual — Install 'danual' shell alias"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  This will add the following line to: $RC"
echo ""
echo "    $ALIAS_LINE"
echo ""
echo "  After installing, type 'danual' in any new terminal to open the manual."
echo ""

if [ -f "$RC" ] && grep -q "alias danual=" "$RC" 2>/dev/null; then
    echo "  ⚠  A 'danual' alias already exists in $RC — nothing to do."
    exit 0
fi

read -r -p "  Proceed? [y/N] " reply
if [[ ! "$reply" =~ ^[Yy]$ ]]; then
    echo "  Cancelled — no changes made."
    exit 0
fi

{
    echo ""
    echo "# Added by The Danual — opens the Hermes manual in your browser"
    echo "$ALIAS_LINE"
} >> "$RC"

echo ""
echo "  ✓ Added to $RC"
echo "  Run:  source $RC"
echo "  Or open a new terminal, then type: danual"
echo ""
