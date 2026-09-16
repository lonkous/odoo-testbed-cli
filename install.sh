#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "$0")" && pwd)"

if ! command -v python3 >/dev/null; then
  echo "Install Python 3.12 or newer first."
  exit 1
fi

python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' || {
  echo "Python 3.12 or newer is required (found $(python3 -c 'import sys; print(sys.version.split()[0])'))."
  exit 1
}

if ! command -v pipx >/dev/null; then
  echo "Install pipx, then re-run ./install.sh"
  echo "  Debian/Ubuntu: sudo apt install pipx && pipx ensurepath"
  echo "  Fedora:        sudo dnf install pipx && pipx ensurepath"
  echo "  macOS:         brew install pipx && pipx ensurepath"
  exit 1
fi

pipx ensurepath >/dev/null 2>&1 || true
# Old package name owned the tb console script; drop it so the new install can take over.
pipx uninstall testbed-tui >/dev/null 2>&1 || true
rm -rf "$root/src/testbed_tui.egg-info"
pipx install --editable "$root" --force

tb_bin="$(command -v tb || true)"
if [[ -z "$tb_bin" ]]; then
  tb_bin="${PIPX_BIN_DIR:-$HOME/.local/bin}/tb"
fi
if [[ ! -x "$tb_bin" ]]; then
  echo "Installed, but tb is not on PATH yet. Open a new terminal and run:"
  echo "  tb setup --defaults"
  echo "  tb doctor"
  exit 0
fi

"$tb_bin" setup --defaults
"$tb_bin" doctor || true

echo
echo "If 'tb' is not found in this shell, open a new terminal."
echo "Next: clone your Odoo repos into ~/Documents (or run tb setup), then tb doctor."
