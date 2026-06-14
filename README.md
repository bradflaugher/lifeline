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

**Required — just one thing:**

| Env var | Purpose |
|---|---|
| `OPENROUTER_API_KEY` | your [OpenRouter key](https://openrouter.ai/keys) — used for every call |

That's it. **Everything below is optional** — sane defaults, ignore unless you
want to tune something:

| Optional env var | Default | Purpose |
|---|---|---|
| `LIFELINE_DEFAULT_FRIEND` | `fusion` | friend used when a call omits one |
| `LIFELINE_CONFIG` | — | path to a custom roster file (else `~/.config/lifeline/lifeline.json`) |
| `LIFELINE_IDLE_TIMEOUT` | `60` | seconds of **silence** before a stream is treated as dead (5–600) |
| `LIFELINE_MAX_SECONDS` | `0` | absolute backstop per call; `0` = unlimited (else 30–7200) |
| `LIFELINE_MAX_TOKENS` | `8000` | max output tokens per call (256–32000) |
| `LIFELINE_MAX_CONCURRENCY` | `4` | max simultaneous calls; excess rejected, not queued (1–64) |
| `LIFELINE_OPENROUTER_URL` | — | override the OpenRouter endpoint (testing / proxies) |

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

### Quick install (one command)

```bash
curl -fsSL https://raw.githubusercontent.com/bradflaugher/lifeline/main/install.sh | bash
```

Clones to `~/lifeline` (override with `LIFELINE_DIR=...`), then registers
`lifeline` with every coding agent it finds that has an `mcp add` command
(Claude Code, Codex, Grok Build) and prints copy-paste snippets for the
config-file agents (Crush, Antigravity, opencode). It's **safe and re-runnable**:
it never edits your config files and skips any agent already configured.

Only prerequisite is `python3` and an **`OPENROUTER_API_KEY`** in your environment
(`export OPENROUTER_API_KEY=sk-or-...` — get one at <https://openrouter.ai/keys>).
The installer tells you if it's missing.

### Manual install (per agent)

Prefer to wire it up yourself? Clone, then follow your agent below:

```bash
git clone https://github.com/bradflaugher/lifeline.git ~/lifeline
```

The server reads the key from its environment, so **no secret is written into a
config file or this repo**. In the snippets below, replace the path with your
absolute path if your agent doesn't expand `~` (most config files don't — use
e.g. `/home/you/lifeline/lifeline.py`).

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
args = ["/home/you/lifeline/lifeline.py"]
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
      "args": ["/home/you/lifeline/lifeline.py"],
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
      "args": ["/home/you/lifeline/lifeline.py"],
      "env": { "OPENROUTER_API_KEY": "sk-or-..." }
    }
  }
}
```

### Grok Build (xAI)

```bash
grok mcp add lifeline -t stdio -c python3 -a ~/lifeline/lifeline.py
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
        "args": ["/home/you/lifeline/lifeline.py"],
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
      "command": ["python3", "/home/you/lifeline/lifeline.py"],
      "enabled": true,
      "environment": { "OPENROUTER_API_KEY": "sk-or-..." }
    }
  }
}
```

Note opencode's shape: `command` is an **array** and the env block is
`environment` (not `env`).

## How the friend is prompted

The system prompt steers the friend toward direct, decisive, actionable answers —
and, crucially, toward the **simplest solution that fully works**. It borrows the
"lazy developer" decision hierarchy from the [ponytail](https://github.com/DietrichGebert/ponytail)
project: before proposing custom code, exhaust *does this need to exist? (YAGNI) →
stdlib → native feature → existing dependency → one-liner → the minimum that works* —
and never recommend speculative abstractions or over-engineering. The same prompt
keeps it *lazy, not negligent*: trust-boundary validation, data-loss handling,
security, and correctness are never traded away. This makes both its advice and its
code audits sharper — it flags real risks instead of padding the answer with bloat.

## Acknowledgments

- [**ponytail**](https://github.com/DietrichGebert/ponytail) by Dietrich Gebert — the
  "lazy developer" / minimalism-first prompt philosophy baked into the advisor system prompt.
- [**OpenRouter Fusion**](https://openrouter.ai/docs/guides/routing/routers/fusion-router) —
  the multi-model deliberation panel behind the default `fusion` friend.

## License

See [LICENSE](LICENSE).
