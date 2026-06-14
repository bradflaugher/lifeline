# lifeline

**Phone-a-friend for coding agents.** When the AI driving your coding session
hits a hard problem, it calls one tool — `phone_a_friend` — to consult a more
powerful or different model and get a second opinion before committing. Like the
*Who Wants to Be a Millionaire* lifeline.

It's a tiny [MCP](https://modelcontextprotocol.io) stdio server (stdlib-only
Python — no `pip install`) that exposes a single tool and routes the question to
a configurable "friend". Everything goes through **OpenRouter** — one
OpenAI-compatible endpoint, one API key (`OPENROUTER_API_KEY`).

## Friends

A *friend* is an advisor backed by an OpenRouter model. Built-in roster:

| Friend | What it is |
|---|---|
| **fusion** | OpenRouter **Fusion** — a panel of frontier models (Claude Opus, GPT, Gemini Pro) deliberate in parallel and a judge synthesizes their answers. Great for "compare and contrast", design trade-offs, and "am I missing something?". |
| **fable** | Anthropic **Claude Fable 5** via OpenRouter (`anthropic/claude-fable-5`) — deepest single-model reasoning for the hardest bugs and long-horizon problems. Requires Fable access on your OpenRouter account; until then the call returns a clear "not available" error. |

## The tool

```
phone_a_friend(question: string, context?: string, friend?: enum)
```

- **question** — the hard question, with enough context to answer standalone.
- **context** — optional extra code / error output / constraints.
- **friend** — which advisor to call (defaults to `$LIFELINE_DEFAULT_FRIEND`, or `fusion`).

The friend can't see your files, so the calling agent is instructed to inline
all relevant code and context.

## Configuration

| Env var | Purpose |
|---|---|
| `OPENROUTER_API_KEY` | **required** — used for every call |
| `LIFELINE_DEFAULT_FRIEND` | default friend when the call omits one (default `fusion`) |
| `LIFELINE_CONFIG` | path to a JSON roster file (else `./lifeline.json` if present) |

Custom roster (`lifeline.json`) — any OpenRouter model can be a friend:

```json
{
  "friends": {
    "fusion":   { "blurb": "Fusion panel.",   "model": "openrouter/fusion" },
    "fable":    { "blurb": "Claude Fable 5.",  "model": "anthropic/claude-fable-5" },
    "deepseek": { "blurb": "Cheap reasoning.", "model": "deepseek/deepseek-v3.2" }
  }
}
```

## Cost & latency

Phoning a friend is **slow (~20–60s) and more expensive than a normal call** —
Fusion fans out to several models, Fable 5 is a frontier model. The tool
description tells the calling model to use it only for genuinely hard problems,
not routine edits. Keep your everyday coding model cheap and reach for the
lifeline on demand.

---

## Install

Requires `python3` and an `OPENROUTER_API_KEY`. The server reads the key from
its environment, so **no secret is written into a config file or this repo** —
make sure `OPENROUTER_API_KEY` is exported in the environment your agent
launches from (or pass it in the agent's MCP `env` block, shown per-tool below).

Clone somewhere stable:

```bash
git clone https://github.com/bradflaugher/lifeline.git ~/lifeline
```

In the snippets below, replace `~/lifeline/lifeline.py` with the absolute path
if your agent doesn't expand `~` (most don't — use e.g. `/home/you/lifeline/lifeline.py`).

### Claude Code

```bash
claude mcp add lifeline -s user -- python3 ~/lifeline/lifeline.py
# pin the key explicitly instead of inheriting it:
# claude mcp add lifeline -s user -e OPENROUTER_API_KEY=sk-or-... -- python3 ~/lifeline/lifeline.py
```

First call prompts once for permission (choose "always allow"); auto-approved in `claude -p`.

### Codex

```bash
codex mcp add lifeline -- python3 ~/lifeline/lifeline.py
# or: codex mcp add lifeline --env OPENROUTER_API_KEY=sk-or-... -- python3 ~/lifeline/lifeline.py
```

Equivalent `~/.codex/config.toml`:

```toml
[mcp_servers.lifeline]
command = "python3"
args = ["/root/lifeline/lifeline.py"]
# env = { OPENROUTER_API_KEY = "sk-or-..." }   # only if not inherited
```

### Crush

`~/.config/crush/crush.json`:

```json
{
  "$schema": "https://charm.land/crush.json",
  "mcp": {
    "lifeline": {
      "type": "stdio",
      "command": "python3",
      "args": ["/root/lifeline/lifeline.py"],
      "env": { "OPENROUTER_API_KEY": "$OPENROUTER_API_KEY" },
      "timeout": 300
    }
  }
}
```

Crush expands `$VAR` in `env`, so the key stays out of the file. Non-interactive
`crush run` auto-approves MCP tools; the interactive TUI prompts once.

### Google Antigravity (CLI + IDE)

Antigravity 2.0, the IDE, and the CLI share one MCP config at
`~/.gemini/config/mcp_config.json` (Settings → Customizations → **Open MCP Config**):

```json
{
  "mcpServers": {
    "lifeline": {
      "command": "python3",
      "args": ["/root/lifeline/lifeline.py"],
      "env": { "OPENROUTER_API_KEY": "sk-or-..." }
    }
  }
}
```

### Grok Build (xAI)

```bash
grok mcp add lifeline -t stdio -c python3 -a /root/lifeline/lifeline.py
# verify: grok mcp list   •   inspect discovery: grok inspect
```

Equivalent project `.mcp.json`:

```json
{
  "mcpServers": [
    {
      "name": "lifeline",
      "transport": {
        "type": "stdio",
        "command": "python3",
        "args": ["/root/lifeline/lifeline.py"],
        "env": { "OPENROUTER_API_KEY": "sk-or-..." }
      }
    }
  ]
}
```

### opencode

`~/.config/opencode/opencode.json` (or project `opencode.json`):

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "lifeline": {
      "type": "local",
      "command": ["python3", "/root/lifeline/lifeline.py"],
      "enabled": true,
      "environment": { "OPENROUTER_API_KEY": "sk-or-..." }
    }
  }
}
```

Note opencode's shape: `command` is an **array** and the env block is
`environment` (not `env`).

## License

See [LICENSE](LICENSE).
