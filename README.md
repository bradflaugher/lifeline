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
| `LIFELINE_CONFIG` | path to a JSON roster file (else `~/.config/lifeline/lifeline.json` if present) |
| `LIFELINE_IDLE_TIMEOUT` | seconds of **silence** before a stream is treated as dead (default `60`, clamped 5–600) |
| `LIFELINE_MAX_SECONDS` | absolute backstop on one call; `0` = unlimited (default `0`, else clamped 30–7200) |
| `LIFELINE_MAX_TOKENS` | max output tokens per call (default `8000`, clamped 256–32000) |
| `LIFELINE_OPENROUTER_URL` | override the OpenRouter endpoint (testing / proxies) |

### How the timeout works

The call is **streamed**, so there's no fixed wall-clock cap that could cut off a
friend who's still thinking. Instead it uses an **idle timeout**: as long as bytes
keep arriving — answer tokens, or OpenRouter's `: OPENROUTER PROCESSING` keep-alives —
the call keeps going, however long it takes. It only fails if the stream goes
*silent* for `LIFELINE_IDLE_TIMEOUT` seconds (dead connection), which it then reports
fast instead of hanging. `LIFELINE_MAX_SECONDS` is an optional hard backstop; left at
`0`, the only absolute ceiling is your **host's** MCP tool timeout. Those defaults
vary and some are short — set them generously for long Fable 5 reasoning:

| Host | Tool-timeout setting | Default | Recommended |
|---|---|---|---|
| Crush | `timeout` (seconds) in `crush.json` | 300 | `1800` |
| Codex | `tool_timeout_sec` in `config.toml` | **60** | `1800` |
| Claude Code | `MCP_TOOL_TIMEOUT` (ms) env | ~28h | leave unset |

The roster is read only from `$LIFELINE_CONFIG` or `~/.config/lifeline/lifeline.json`
— never the current directory — so launching an agent inside an untrusted repo
can't silently reconfigure who you phone. Each friend needs a non-empty string
`model`; invalid entries are ignored (logged to stderr). Example roster — any
OpenRouter model can be a friend:

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
Claude Code's MCP tool timeout already defaults to ~28h, so long streaming calls
aren't cut off — no extra config needed. (To shorten it, set `MCP_TOOL_TIMEOUT` in ms.)

### Codex

```bash
codex mcp add lifeline -- python3 ~/lifeline/lifeline.py
# or: codex mcp add lifeline --env OPENROUTER_API_KEY=sk-or-... -- python3 ~/lifeline/lifeline.py
```

Then **raise the tool timeout** — Codex defaults to **60s**, which cuts off most
phone-a-friend calls. Edit `~/.codex/config.toml`:

```toml
[mcp_servers.lifeline]
command = "python3"
args = ["/root/lifeline/lifeline.py"]
startup_timeout_sec = 30
tool_timeout_sec = 1800   # default is 60s — far too short for a deliberation panel
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
      "timeout": 1800
    }
  }
}
```

`timeout` (seconds) is Crush's MCP tool timeout — set it generously (here 30 min)
so a long streaming call isn't cut off; lifeline's idle timeout handles dead ones.
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
