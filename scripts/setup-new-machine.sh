#!/bin/sh
# Verify a fresh checkout of Boring Meter. Installs nothing and changes no settings.
set -u
cd "$(dirname "$0")/.." || exit 1

ok=1
check() {
  if command -v "$1" >/dev/null 2>&1; then
    printf 'ok      %s: %s\n' "$1" "$($1 --version 2>&1 | head -1)"
  else
    printf 'MISSING %s (%s)\n' "$1" "$2"
    ok=0
  fi
}

check git "brew install git"
check python3 "brew install python@3.12, or xcode-select --install"
check gh "optional: brew install gh"
check claude "optional for tests: install Claude Code from https://code.claude.com/docs"

if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
  echo "MISSING Python 3.9 or newer"
  exit 1
fi

echo
echo "Running the test suite..."
log=$(mktemp)
if python3 -m unittest discover -s tests -t . >"$log" 2>&1; then
  tail -3 "$log"
else
  tail -30 "$log"
  echo "Tests FAILED"
  ok=0
fi
rm -f "$log"

echo
./bin/boring-meter doctor

if [ "$ok" -eq 1 ]; then
  echo
  echo "Ready. Next: see MIGRATION_GUIDE.md step 5 to install the plugin in Claude Code."
else
  echo
  echo "Fix the items above, then run this script again."
  exit 1
fi
