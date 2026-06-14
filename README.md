# lifeline

**Phone-a-friend for coding agents.** When the AI driving your coding session
hits a hard problem, it calls one tool — `phone_a_friend` — to consult a more
powerful or different model and get a second opinion before committing. Like the
*Who Wants to Be a Millionaire* lifeline.

It's a tiny [MCP](https://modelcontextprotocol.io) stdio server (stdlib-only
Python — no `pip install`) that exposes a single tool and routes the question to
a configurable "friend".

## Friends

A *friend* is an advisor backed by one or more model routes. Two transports are
built in:

| Transport | Reaches |
|---|---|
| `openrouter` | any OpenRouter model (OpenAI-compatible), incl. the `openrouter/fusion` deliberation panel |
| `anthropic` | Anthropic's native Messages API (Claude Fable 5 request shape: thinking always-on, `effort` control, server-side fallback to Opus on a safety refusal) |

Built-in roster:

| Friend | What it is | Needs |
|---|---|---|
| **fusion** | OpenRouter **Fusion** — a panel of frontier models (Claude Opus, GPT, Gemini Pro) deliberate in parallel and a judge synthesizes. Great for "compare and contrast", design trade-offs, and "am I missing something?". | `OPENROUTER_API_KEY` |
| **fable** | Anthropic **Claude Fable 5** — deepest single-model reasoning for the hardest bugs and long-horizon problems. Prefers the native Anthropic API; falls back to Fable 5 **via OpenRouter** if that's the only key you have. | `ANTHROPIC_API_KEY` (preferred) or `OPENROUTER_API_KEY` |

The tool only advertises friends whose credentials are present, and the
`friend` argument is an enum of those — so the calling model always sees a valid
menu.

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
| `OPENROUTER_API_KEY` | enables `openrouter`-backed routes |
| `ANTHROPIC_API_KEY` | enables `anthropic`-backed routes |
| `LIFELINE_DEFAULT_FRIEND` | default friend when the call omits one (default `fusion`) |
| `LIFELINE_CONFIG` | path to a JSON roster file (else `./lifeline.json` if present) |

Custom roster (`lifeline.json`):

```json
{
  "friends": {
    "fusion":  { "blurb": "Fusion panel.", "routes": [{ "provider": "openrouter", "model": "openrouter/fusion" }] },
    "fable":   { "blurb": "Claude Fable 5.", "routes": [
        { "provider": "anthropic",  "model": "claude-fable-5", "effort": "high" },
        { "provider": "openrouter", "model": "anthropic/claude-fable-5" } ] },
    "deepseek":{ "blurb": "Cheap reasoning.", "routes": [{ "provider": "openrouter", "model": "deepseek/deepseek-v3.2" }] }
  }
}
```

A friend's `routes` are tried in order; the first whose provider has a key wins.
That's how `fable` uses the native Anthropic API when you have the key and
transparently falls back to OpenRouter when you don't.

## Cost & latency

Phoning a friend is **slow (~20–60s) and more expensive than a normal call** —
Fusion fans out to several models, Fable 5 is a frontier model. The tool
description tells the calling model to use it only for genuinely hard problems,
not routine edits. Keep your everyday coding model cheap and reach for the
lifeline on demand.

---

## Install

Requires `python3`. The server reads API keys from its environment, so **no
secret is ever written into a config file or this repo** — make sure the keys
are exported in the environment your agent launches from (or pass them in the
agent's MCP env block, shown below).

Clone somewhere stable:

```bash
git clone https://github.com/bradflaugher/lifeline.git ~/lifeline
```

### Claude Code

```bash
claude mcp add lifeline -s user -- python3 ~/lifeline/lifeline.py
```

This inherits your shell environment (so an exported `OPENROUTER_API_KEY` /
`ANTHROPIC_API_KEY` is seen). To pin a key explicitly instead:

```bash
claude mcp add lifeline -s user -e OPENROUTER_API_KEY=sk-or-... -- python3 ~/lifeline/lifeline.py
```

The first call prompts once for permission — choose "always allow" (or it's
auto-approved in non-interactive `claude -p` runs).

### Codex

```bash
codex mcp add lifeline -- python3 ~/lifeline/lifeline.py
# or pin a key: codex mcp add lifeline --env OPENROUTER_API_KEY=sk-or-... -- python3 ~/lifeline/lifeline.py
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

## License

See [LICENSE](LICENSE).
