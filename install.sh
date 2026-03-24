#!/bin/bash
set -euo pipefail

# prime installer — preload codebases into Claude Code's context window

echo "=== Prime Installer ==="
echo ""

# Check prereqs
command -v python3 >/dev/null || { echo "ERROR: python3 required"; exit 1; }
command -v claude >/dev/null || { echo "ERROR: claude CLI required (https://docs.anthropic.com/en/docs/claude-code)"; exit 1; }

PKG_DIR="$(cd "$(dirname "$0")" && pwd)"
PRIME_HOME="$HOME/.prime"
BIN_DIR="$HOME/.local/bin"

# Create directories
mkdir -p "$PRIME_HOME" "$BIN_DIR"

# Copy core files
echo "Installing prime to $PRIME_HOME..."
cp "$PKG_DIR/lib/prime_build.py" "$PRIME_HOME/"
chmod +x "$PRIME_HOME/prime_build.py"

# Install the wrapper script, pointing to installed location
cat > "$BIN_DIR/prime" << 'WRAPPER'
#!/bin/bash
set -euo pipefail

PRIME_BUILD="$HOME/.prime/prime_build.py"

case "${1:-}" in
    --init|--scan|--list|--version|-h|--help|--dry-run)
        exec python3 "$PRIME_BUILD" "$@"
        ;;
esac

[ -n "${1:-}" ] || { python3 "$PRIME_BUILD" --help; exit 1; }

PROJECT="$*"

python3 "$PRIME_BUILD" "$PROJECT"
CONTEXT_FILE=$(cat /tmp/prime-session 2>/dev/null)
[ -f "$CONTEXT_FILE" ] || { echo "error: no context file generated"; exit 1; }

CWD=$(python3 -c "
import json, os, sys
for name in ['.primerc', 'prime.json', '.prime.json']:
    if os.path.isfile(name):
        d = json.load(open(name))
        print(os.path.expanduser(d.get('path', os.getcwd())))
        sys.exit(0)
registry = os.path.expanduser('~/.prime/projects.json')
if os.path.isfile(registry):
    d = json.load(open(registry))
    q = '$PROJECT'.replace('-',' ').lower()
    for name, config in d.items():
        if q in name.lower().replace('-',' '):
            print(os.path.expanduser(config['path']))
            sys.exit(0)
print(os.getcwd())
" 2>/dev/null || echo "$(pwd)")

echo ""
echo "  Ready. All files pre-loaded with line numbers."
echo ""
cd "$CWD"
exec claude --append-system-prompt-file "$CONTEXT_FILE"
WRAPPER
chmod +x "$BIN_DIR/prime"

# Create projects.json if not exists
if [ ! -f "$PRIME_HOME/projects.json" ]; then
    cp "$PKG_DIR/templates/projects.json.example" "$PRIME_HOME/projects.json"
    echo "  Created $PRIME_HOME/projects.json (edit to add your projects)"
else
    echo "  projects.json already exists, keeping yours."
fi

echo ""
echo "=== Installed ==="
echo ""
echo "Make sure $BIN_DIR is in your PATH:"
echo '  export PATH="$HOME/.local/bin:$PATH"'
echo ""
echo "Quick start:"
echo "  cd ~/your-project"
echo "  prime --init          # scan and create .primerc"
echo "  prime .               # launch Claude with full context"
echo ""
echo "Or use the central registry:"
echo "  Edit ~/.prime/projects.json"
echo "  prime my-project"
echo ""
echo "Uninstall: bash $(dirname "$0")/uninstall.sh"
