#!/usr/bin/env bash
# lifeline installer — register the phone_a_friend MCP server with the coding
# agents you already have installed.
#
# Safe by design: it only calls each agent's own `mcp add` command and PRINTS
# copy-paste snippets for config-file agents. It never edits your config files,
# and it skips any agent that already has lifeline configured (so it won't clobber
# settings you've tuned). Re-running it is safe.
#
#   curl -fsSL https://raw.githubusercontent.com/bradflaugher/lifeline/main/install.sh | bash
#
# Optional env: LIFELINE_DIR=/path   where to clone (default ~/lifeline)
set -euo pipefail

REPO="https://github.com/bradflaugher/lifeline.git"
DIR="${LIFELINE_DIR:-$HOME/lifeline}"
b() { printf '\n\033[1m%s\033[0m\n' "$*"; }   # bold heading
i() { printf '  %s\n' "$*"; }                 # indented line

b "lifeline installer"
command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 is required."; exit 1; }

# --- get the code ---
if [ -d "$DIR/.git" ]; then
  i "Updating $DIR"
  git -C "$DIR" pull --quiet --ff-only 2>/dev/null || i "(kept current checkout)"
elif [ -f "$DIR/lifeline.py" ]; then
  i "Using $DIR"
else
  command -v git >/dev/null 2>&1 || { echo "ERROR: git is required to clone."; exit 1; }
  i "Cloning $REPO -> $DIR"
  git clone --quiet "$REPO" "$DIR"
fi
SERVER="$DIR/lifeline.py"
[ -f "$SERVER" ] || { echo "ERROR: $SERVER not found."; exit 1; }
i "Server: $SERVER"

# --- the one required setting ---
b "Required: OPENROUTER_API_KEY"
if [ -n "${OPENROUTER_API_KEY:-}" ]; then
  i "Set — this is the ONLY thing lifeline requires."
else
  i "NOT set. It's the only required setting. Get a key at https://openrouter.ai/keys, then:"
  i "    export OPENROUTER_API_KEY=sk-or-...      # add to ~/.bashrc or ~/.zshrc"
  i "Agents launched from that shell inherit it."
fi

# --- register with detected agents (CLI = safe + idempotent) ---
b "Registering with installed agents"
added=0; codex_new=0

try_add() {  # label  get-cmd... '|' add-cmd...
  local label="$1"; shift
  local get=(); while [ "$1" != "|" ]; do get+=("$1"); shift; done; shift
  if "${get[@]}" >/dev/null 2>&1; then
    i "$label: already configured — skipping (your settings kept)"
    return 1
  fi
  if "$@" >/dev/null 2>&1; then i "$label: configured"; added=$((added+1)); return 0; fi
  i "$label: detected but 'mcp add' failed — configure manually"; return 1
}

command -v claude >/dev/null 2>&1 && \
  try_add "Claude Code (user scope)" claude mcp get lifeline '|' \
          claude mcp add lifeline -s user -- python3 "$SERVER" || true

if command -v codex >/dev/null 2>&1; then
  try_add "Codex" codex mcp get lifeline '|' \
          codex mcp add lifeline -- python3 "$SERVER" && codex_new=1 || true
fi

command -v grok >/dev/null 2>&1 && \
  try_add "Grok Build" grok mcp get lifeline '|' \
          grok mcp add lifeline -t stdio -c python3 -a "$SERVER" || true

[ "$added" -eq 0 ] && i "(nothing newly added — agents missing or already configured)"

# --- Codex timeout note (only when we just added it) ---
if [ "$codex_new" -eq 1 ]; then
  b "Codex: raise the tool timeout (important)"
  i "Codex defaults to a 60s tool timeout — too short; it cuts off most calls."
  i "Add these under [mcp_servers.lifeline] in ~/.codex/config.toml:"
  i "    startup_timeout_sec = 30"
  i "    tool_timeout_sec = 1800"
fi

# --- config-file agents: print snippets (installer never edits your files) ---
b "Config-file agents — paste these (using your path)"
i "Crush  ~/.config/crush/crush.json  (inside \"mcp\": { ... }):"
cat <<EOF
      "lifeline": { "type": "stdio", "command": "python3",
        "args": ["$SERVER"],
        "env": { "OPENROUTER_API_KEY": "\$OPENROUTER_API_KEY" }, "timeout": 1800 }
EOF
i "Antigravity  ~/.gemini/config/mcp_config.json  (inside \"mcpServers\": { ... }):"
cat <<EOF
      "lifeline": { "command": "python3", "args": ["$SERVER"],
        "env": { "OPENROUTER_API_KEY": "sk-or-..." } }
EOF
i "opencode  ~/.config/opencode/opencode.json  (inside \"mcp\": { ... }):"
cat <<EOF
      "lifeline": { "type": "local", "command": ["python3", "$SERVER"],
        "enabled": true, "environment": { "OPENROUTER_API_KEY": "sk-or-..." } }
EOF

# --- smoke test (no API call: initialize + tools/list only) ---
b "Smoke test"
if printf '%s\n%s\n' \
   '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}' \
   '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
   | python3 "$SERVER" 2>/dev/null | grep -q phone_a_friend; then
  i "Server starts and exposes phone_a_friend — OK"
else
  i "Smoke test FAILED — run 'python3 $SERVER' and check for errors."
fi

b "Done"
i "In any configured agent, just ask it to \"phone a friend\" on a hard problem."
i "Everything beyond OPENROUTER_API_KEY is optional tuning — see the README."
