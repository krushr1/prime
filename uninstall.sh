#!/bin/bash
set -euo pipefail

echo "=== Prime Uninstaller ==="
echo ""

rm -f "$HOME/.local/bin/prime"
echo "  Removed $HOME/.local/bin/prime"

if [ -f "$HOME/.prime/prime_build.py" ]; then
    rm "$HOME/.prime/prime_build.py"
    echo "  Removed $HOME/.prime/prime_build.py"
fi

echo ""
echo "Kept: ~/.prime/projects.json (your project configs)"
echo "To fully remove: rm -rf ~/.prime"
