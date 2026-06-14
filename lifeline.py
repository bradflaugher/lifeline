#!/usr/bin/env python3
"""lifeline — a "phone a friend" tool for coding agents (MCP stdio server).

Like the Who-Wants-to-Be-a-Millionaire lifeline: when the agent driving your
coding session (crush, Claude Code, Codex, …) hits a hard problem, it calls
`phone_a_friend` to consult a more powerful / different model and get a
second opinion before committing.

Backends ("friends") are pluggable. Two transports are built in:

  * openrouter — any model on OpenRouter (OpenAI-compatible chat completions),
                 including the `openrouter/fusion` multi-model deliberation panel.
  * anthropic  — Anthropic's native Messages API, with the Claude Fable 5
                 request shape (thinking always-on so it's omitted; depth via
                 output_config.effort; server-side fallback to Opus on refusal).

Default friends:
  * fusion — OpenRouter Fusion panel (Opus + GPT + Gemini Pro deliberate, judge synthesizes).
  * fable  — Claude Fable 5. Prefers the native Anthropic API (ANTHROPIC_API_KEY);
             falls back to Fable 5 via OpenRouter (OPENROUTER_API_KEY) if that's all you have.

Override the roster with a JSON file at $LIFELINE_CONFIG or ./lifeline.json
(see README). Pick the default friend with $LIFELINE_DEFAULT_FRIEND.

Stdlib only (json + urllib) — no pip install, so it runs unchanged wherever the
host agent launches it. MCP stdio transport = newline-delimited JSON-RPC 2.0.
"""

import json
import os
import sys
import urllib.request
import urllib.error

SERVER_NAME = "lifeline"
SERVER_VERSION = "1.0.0"
DEFAULT_PROTOCOL = "2025-06-18"

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
ANTHROPIC_FALLBACK_MODEL = "claude-opus-4-8"  # rescues a spurious Fable-5 refusal
ANTHROPIC_FALLBACK_BETA = "server-side-fallback-2026-06-01"

MAX_TOKENS = 8000
TIMEOUT = 240

SYSTEM_PROMPT = (
    "You are the expert a coding agent phoned as a lifeline because it is stuck "
    "or wants a high-confidence second opinion. Give a direct, decisive, "
    "technically precise answer it can act on immediately. Prefer concrete code, "
    "exact commands, and a clear recommendation over hedging. If the question is "
    "underspecified, state the most likely intent and answer that, flagging any "
    "critical assumption. You cannot see the caller's files — reason only from "
    "what is in the question."
)

# --- Friend roster -----------------------------------------------------------

DEFAULT_FRIENDS = {
    "fusion": {
        "blurb": "OpenRouter Fusion — a panel of frontier models (Claude Opus, GPT, "
                 "Gemini Pro) deliberate in parallel and a judge synthesizes their "
                 "answers. Best for second opinions, design trade-offs, "
                 "compare-and-contrast, and 'am I missing something?' checks.",
        "routes": [{"provider": "openrouter", "model": "openrouter/fusion"}],
    },
    "fable": {
        "blurb": "Claude Fable 5 — Anthropic's most capable model; deep single-model "
                 "reasoning for the hardest bugs, tricky algorithms, and long-horizon "
                 "design problems.",
        # First viable route wins: native Anthropic API if you have the key,
        # otherwise Fable 5 through OpenRouter.
        "routes": [
            {"provider": "anthropic", "model": "claude-fable-5", "effort": "high"},
            {"provider": "openrouter", "model": "anthropic/claude-fable-5"},
        ],
    },
}


def load_friends():
    friends = json.loads(json.dumps(DEFAULT_FRIENDS))  # deep copy
    path = os.environ.get("LIFELINE_CONFIG")
    if not path and os.path.exists("lifeline.json"):
        path = "lifeline.json"
    if path and os.path.exists(path):
        try:
            cfg = json.load(open(path))
            friends.update(cfg.get("friends", cfg))
        except Exception:  # noqa: BLE001 — a broken config shouldn't kill the server
            pass
    return friends


def provider_available(provider):
    if provider == "openrouter":
        return bool(os.environ.get("OPENROUTER_API_KEY"))
    if provider == "anthropic":
        return bool(os.environ.get("ANTHROPIC_API_KEY"))
    return False


def pick_route(friend):
    """First route whose provider has credentials, or None."""
    for route in friend.get("routes", []):
        if provider_available(route.get("provider")):
            return route
    return None


def available_friends(friends):
    return {name: f for name, f in friends.items() if pick_route(f) is not None}


def default_friend_name(friends):
    avail = available_friends(friends)
    pref = os.environ.get("LIFELINE_DEFAULT_FRIEND", "fusion")
    if pref in avail:
        return pref
    return next(iter(avail), None)


# --- Transports --------------------------------------------------------------

def _post(url, body, headers):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.load(resp)


def call_openrouter(model, prompt):
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": MAX_TOKENS,
    }
    headers = {
        "Authorization": "Bearer " + os.environ["OPENROUTER_API_KEY"],
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/bradflaugher/lifeline",
        "X-Title": "lifeline phone_a_friend",
    }
    data = _post(OPENROUTER_URL, body, headers)
    answer = data["choices"][0]["message"]["content"]
    judge = data.get("model", model)
    cost = (data.get("usage") or {}).get("cost")
    meta = f"{judge}" + (f" · cost ${cost:.4f}" if isinstance(cost, (int, float)) else "")
    return answer, meta


def call_anthropic(model, prompt, effort="high"):
    body = {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": prompt}],
        "output_config": {"effort": effort},
        # NOTE: no `thinking` param — Fable 5 has thinking always on and rejects
        # an explicit thinking config; depth is controlled via output_config.effort.
    }
    headers = {
        "x-api-key": os.environ["ANTHROPIC_API_KEY"],
        "anthropic-version": ANTHROPIC_VERSION,
        "Content-Type": "application/json",
    }
    # Opt into a server-side fallback so a spurious safety refusal on adjacent
    # work doesn't kill the lifeline (Fable 5 can return stop_reason=refusal).
    if model != ANTHROPIC_FALLBACK_MODEL:
        headers["anthropic-beta"] = ANTHROPIC_FALLBACK_BETA
        body["fallbacks"] = [{"model": ANTHROPIC_FALLBACK_MODEL}]

    data = _post(ANTHROPIC_URL, body, headers)
    if data.get("stop_reason") == "refusal":
        det = data.get("stop_details") or {}
        return None, f"Anthropic declined this request (category: {det.get('category')})."
    text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    served = data.get("model", model)
    usage = data.get("usage") or {}
    meta = f"{served} · {usage.get('input_tokens', '?')}in/{usage.get('output_tokens', '?')}out tok"
    return text, None if text else "Empty response from Anthropic."


def dispatch(route, prompt):
    provider = route.get("provider")
    model = route.get("model")
    if provider == "openrouter":
        return call_openrouter(model, prompt)
    if provider == "anthropic":
        return call_anthropic(model, prompt, route.get("effort", "high"))
    return None, f"Unknown provider: {provider}"


# --- MCP plumbing ------------------------------------------------------------

def build_tool_schema(friends):
    avail = available_friends(friends)
    default = default_friend_name(friends)
    roster = "\n".join(f"  - {name}: {f['blurb']}" for name, f in avail.items()) or \
        "  (none — set OPENROUTER_API_KEY and/or ANTHROPIC_API_KEY)"
    desc = (
        "Phone a friend — consult a more powerful or different AI for help on a HARD "
        "problem where you are stuck or want a high-confidence second opinion (subtle "
        "bugs, architecture/design trade-offs, tricky algorithms, ambiguous requirements, "
        "'am I missing something?'). Slow (~20-60s) and more expensive than a normal "
        "call, so do NOT use it for routine edits or simple lookups. The friend cannot "
        "see your files — put all relevant code, errors, and context in the question.\n\n"
        "Available friends:\n" + roster
    )
    if default:
        desc += f"\n\nDefault friend if unspecified: {default}."
    schema = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The hard question, with enough context to answer standalone.",
            },
            "context": {
                "type": "string",
                "description": "Optional extra context: relevant code, error output, constraints.",
            },
        },
        "required": ["question"],
    }
    if avail:
        schema["properties"]["friend"] = {
            "type": "string",
            "enum": list(avail.keys()),
            "description": f"Which friend to call. Defaults to '{default}'.",
        }
    return {"name": "phone_a_friend", "description": desc, "inputSchema": schema}


def run_phone_a_friend(args, friends):
    question = args.get("question")
    if not question:
        return "Error: 'question' is required.", True

    avail = available_friends(friends)
    if not avail:
        return ("No friends are reachable. Set OPENROUTER_API_KEY and/or "
                "ANTHROPIC_API_KEY in the lifeline server's environment."), True

    name = args.get("friend") or default_friend_name(friends)
    if name not in avail:
        return (f"Unknown or unavailable friend '{name}'. "
                f"Available: {', '.join(avail)}."), True

    route = pick_route(avail[name])
    prompt = question if not args.get("context") else \
        f"{question}\n\n--- Additional context ---\n{args['context']}"

    try:
        answer, meta = dispatch(route, prompt)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:400]
        return f"phone_a_friend error ({name}): HTTP {e.code}: {detail}", True
    except Exception as e:  # noqa: BLE001
        return f"phone_a_friend error ({name}): {e}", True

    if answer is None:
        return f"phone_a_friend ({name}): {meta}", True
    return f"{answer}\n\n---\n_via {name} ({meta})_", False


def send(msg):
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def handle(msg, friends):
    method = msg.get("method")
    req_id = msg.get("id")

    if method == "initialize":
        proto = (msg.get("params") or {}).get("protocolVersion", DEFAULT_PROTOCOL)
        send({"jsonrpc": "2.0", "id": req_id, "result": {
            "protocolVersion": proto,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        }})
        return

    if method == "tools/list":
        send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": [build_tool_schema(friends)]}})
        return

    if method == "tools/call":
        params = msg.get("params") or {}
        if params.get("name") != "phone_a_friend":
            send({"jsonrpc": "2.0", "id": req_id,
                  "error": {"code": -32602, "message": f"Unknown tool: {params.get('name')}"}})
            return
        text, is_error = run_phone_a_friend(params.get("arguments") or {}, friends)
        result = {"content": [{"type": "text", "text": text}]}
        if is_error:
            result["isError"] = True
        send({"jsonrpc": "2.0", "id": req_id, "result": result})
        return

    if method == "ping":
        send({"jsonrpc": "2.0", "id": req_id, "result": {}})
        return

    if req_id is not None:  # unknown request (not a notification)
        send({"jsonrpc": "2.0", "id": req_id,
              "error": {"code": -32601, "message": f"Method not found: {method}"}})


def main():
    friends = load_friends()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            handle(msg, friends)
        except Exception as e:  # noqa: BLE001 — one bad message must not kill the server
            if msg.get("id") is not None:
                send({"jsonrpc": "2.0", "id": msg["id"],
                      "error": {"code": -32603, "message": f"Internal error: {e}"}})


if __name__ == "__main__":
    main()
