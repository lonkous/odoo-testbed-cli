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

pipx_bin="${PIPX_BIN_DIR:-$HOME/.local/bin}"
tb_bin="$(command -v tb || true)"
if [[ -z "$tb_bin" ]]; then
  tb_bin="$pipx_bin/tb"
fi
mcp_bin="$(command -v tb-mcp || true)"
if [[ -z "$mcp_bin" ]]; then
  mcp_bin="$pipx_bin/tb-mcp"
fi

python3 - "$mcp_bin" <<'PY'
import json
import sys
from pathlib import Path

command = sys.argv[1]
path = Path.home() / ".cursor" / "mcp.json"
path.parent.mkdir(parents=True, exist_ok=True)
data = {}
if path.exists():
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        data = {}
if not isinstance(data, dict):
    data = {}
servers = data.setdefault("mcpServers", {})
if not isinstance(servers, dict):
    servers = {}
    data["mcpServers"] = servers
servers["tb"] = {"type": "stdio", "command": command}
path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
print(f"Cursor MCP: {path}")
PY

skill_src="$root/src/testbed_cli/templates/cursor/SKILL.md"
skill_dest="$HOME/.cursor/skills/tb/SKILL.md"
mkdir -p "$(dirname "$skill_dest")"
command cp "$skill_src" "$skill_dest"
echo "Cursor skill: $skill_dest"

if [[ ! -x "$tb_bin" ]]; then
  echo "Installed, but tb is not on PATH yet. Open a new terminal and run:"
  echo "  tb setup --defaults"
  echo "  tb doctor"
  echo "Enable the tb MCP server in Cursor Settings → Tools & MCP."
  exit 0
fi

"$tb_bin" setup --defaults
"$tb_bin" doctor || true

echo
echo "If 'tb' is not found in this shell, open a new terminal."
echo "Enable the tb MCP server in Cursor Settings → Tools & MCP."
echo "Next: clone your Odoo repos into ~/Documents (or run tb setup), then tb doctor."
