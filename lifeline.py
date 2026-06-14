#!/usr/bin/env python3
"""lifeline — a "phone a friend" tool for coding agents (MCP stdio server).

Like the Who-Wants-to-Be-a-Millionaire lifeline: when the agent driving your
coding session (crush, Claude Code, Codex, Antigravity, Grok, opencode, …) hits
a hard problem, it calls `phone_a_friend` to consult a more powerful or
different model and get a second opinion before committing.

Everything routes through **OpenRouter** (one OpenAI-compatible endpoint, one
API key). Backends ("friends") are pluggable; the built-in roster is:

  * fusion — OpenRouter Fusion: a panel of frontier models (Opus, GPT, Gemini
             Pro) deliberate in parallel and a judge synthesizes their answers.
  * fable  — Claude Fable 5 (via OpenRouter: `anthropic/claude-fable-5`).
             Requires Fable access on your OpenRouter account; until then the
             call returns a clear "not available" error.

Override the roster with a JSON file at $LIFELINE_CONFIG or
~/.config/lifeline/lifeline.json (see README). Pick the default friend with
$LIFELINE_DEFAULT_FRIEND.

Stdlib only (json + urllib + threading) — no pip install, so it runs unchanged
wherever the host agent launches it. MCP stdio transport = newline-delimited
JSON-RPC 2.0; the tool call is dispatched on a worker thread so the read loop
keeps answering `ping` while a long call is in flight.
"""

import json
import os
import sys
import threading
import urllib.request
import urllib.error

SERVER_NAME = "lifeline"
SERVER_VERSION = "2.0.0"
DEFAULT_PROTOCOL = "2025-06-18"
SUPPORTED_PROTOCOLS = {"2025-06-18", "2025-03-26", "2024-11-05"}

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MAX_RESPONSE_BYTES = 16 * 1024 * 1024  # hard cap on an OpenRouter response body
MAX_QUESTION_CHARS = 100_000
MAX_CONTEXT_CHARS = 400_000

# JSON-RPC error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

SYSTEM_PROMPT = (
    "You are the expert a coding agent phoned as a lifeline because it is stuck "
    "or wants a high-confidence second opinion. Give a direct, decisive, "
    "technically precise answer it can act on immediately. Prefer concrete code, "
    "exact commands, and a clear recommendation over hedging. If the question is "
    "underspecified, state the most likely intent and answer that, flagging any "
    "critical assumption. You cannot see the caller's files — reason only from "
    "what is in the question."
)

# Protect the protocol stream: capture the real stdout, then point sys.stdout at
# stderr so a stray print() anywhere can never corrupt the JSON-RPC channel.
_REAL_STDOUT = sys.stdout
sys.stdout = sys.stderr
_OUT_LOCK = threading.Lock()

# --- Environment-tunable settings --------------------------------------------

def get_api_key():
    return (os.environ.get("OPENROUTER_API_KEY") or "").strip() or None


def _env_int(name, default, lo, hi):
    try:
        return max(lo, min(hi, int(os.environ[name])))
    except (KeyError, ValueError):
        return default


def get_timeout():
    return _env_int("LIFELINE_TIMEOUT", 180, 10, 600)


def get_max_tokens():
    return _env_int("LIFELINE_MAX_TOKENS", 8000, 256, 32000)


# --- Friend roster (all routes go through OpenRouter) ------------------------

DEFAULT_FRIENDS = {
    "fusion": {
        "blurb": "OpenRouter Fusion — a panel of frontier models (Claude Opus, GPT, "
                 "Gemini Pro) deliberate in parallel and a judge synthesizes their "
                 "answers. Best for second opinions, design trade-offs, "
                 "compare-and-contrast, and 'am I missing something?' checks.",
        "model": "openrouter/fusion",
    },
    "fable": {
        "blurb": "Claude Fable 5 — Anthropic's most capable model; deep single-model "
                 "reasoning for the hardest bugs, tricky algorithms, and long-horizon "
                 "design problems. (Requires Fable access on your OpenRouter account.)",
        "model": "anthropic/claude-fable-5",
    },
}


def _config_path():
    explicit = os.environ.get("LIFELINE_CONFIG")
    if explicit:
        return explicit
    home = os.path.join(os.path.expanduser("~"), ".config", "lifeline", "lifeline.json")
    return home if os.path.exists(home) else None


def load_friends():
    """Built-in roster, optionally extended/overridden by a validated config file.

    The config is read only from $LIFELINE_CONFIG or ~/.config/lifeline/lifeline.json
    — never the current working directory, so launching an agent inside an untrusted
    repo can't silently reconfigure who you phone.
    """
    friends = json.loads(json.dumps(DEFAULT_FRIENDS))  # deep copy
    path = _config_path()
    if not path or not os.path.exists(path):
        return friends
    try:
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception as e:  # noqa: BLE001 — a broken config must not kill the server
        print(f"lifeline: failed to load config {path!r}: {e!r}", file=sys.stderr)
        return friends

    raw = cfg.get("friends") if isinstance(cfg, dict) and "friends" in cfg else cfg
    if not isinstance(raw, dict):
        print(f"lifeline: config {path!r} has no usable 'friends' object", file=sys.stderr)
        return friends
    for name, spec in raw.items():
        if (isinstance(name, str) and name and isinstance(spec, dict)
                and isinstance(spec.get("model"), str) and spec["model"].strip()):
            entry = {"model": spec["model"].strip()}
            entry["blurb"] = spec["blurb"] if isinstance(spec.get("blurb"), str) else entry["model"]
            friends[name] = entry
        else:
            print(f"lifeline: ignoring invalid friend {name!r} in config", file=sys.stderr)
    return friends


def default_friend_name(friends):
    pref = os.environ.get("LIFELINE_DEFAULT_FRIEND", "fusion")
    if pref in friends:
        return pref
    return next(iter(friends), None)


# --- OpenRouter transport ----------------------------------------------------

def call_openrouter(model, prompt):
    """Return (answer, meta). Raises on transport/HTTP/shape failure."""
    api_key = get_api_key()
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set")

    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": get_max_tokens(),
    }
    headers = {
        "Authorization": "Bearer " + api_key,
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/bradflaugher/lifeline",
        "X-Title": "lifeline phone_a_friend",
    }
    req = urllib.request.Request(OPENROUTER_URL, data=json.dumps(body).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=get_timeout()) as resp:
        raw = resp.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise RuntimeError("OpenRouter response exceeded size cap")

    # On slow/long requests OpenRouter emits ": OPENROUTER PROCESSING" SSE keep-alive
    # comment lines before the JSON body, even on the non-streaming endpoint
    # (confirmed empirically — a big/slow call returns these). The body is a single
    # JSON document and JSON escapes newlines, so any physical line that starts with
    # ':' is a keep-alive comment, never response content — safe to drop.
    text = raw.decode("utf-8", "replace")
    if "\n:" in text or text.lstrip().startswith(":"):
        text = "\n".join(line for line in text.splitlines() if not line.startswith(":"))
    data = json.loads(text)

    if not isinstance(data, dict):
        raise RuntimeError("unexpected OpenRouter response (not an object)")
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        # OpenRouter can return HTTP 200 with an {"error": {...}} body and no choices.
        upstream = (data.get("error") or {}).get("message") if isinstance(data.get("error"), dict) else None
        raise RuntimeError(f"upstream error: {upstream or 'no choices returned'}")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    answer = (message or {}).get("content")
    if not isinstance(answer, str) or not answer.strip():
        raise RuntimeError("upstream returned no text content")

    served = data.get("model", model)
    cost = (data.get("usage") or {}).get("cost") if isinstance(data.get("usage"), dict) else None
    meta = served
    if isinstance(cost, (int, float)) and not isinstance(cost, bool):
        meta += f" · cost ${cost:.4f}"
    return answer, meta


# --- Tool --------------------------------------------------------------------

def build_tool_schema(friends):
    default = default_friend_name(friends)
    roster = "\n".join(f"  - {name}: {f['blurb']}" for name, f in friends.items())
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
    return {
        "name": "phone_a_friend",
        "description": desc,
        "inputSchema": {
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
                "friend": {
                    "type": "string",
                    "enum": list(friends.keys()),
                    "description": f"Which friend to call. Defaults to '{default}'.",
                },
            },
            "required": ["question"],
        },
    }


def run_phone_a_friend(args, friends):
    """Return (text, is_error). Validates untrusted tool input."""
    if not isinstance(args, dict):
        return "Error: tool arguments must be an object.", True

    question = args.get("question")
    if not isinstance(question, str) or not question.strip():
        return "Error: 'question' must be a non-empty string.", True
    if len(question) > MAX_QUESTION_CHARS:
        return f"Error: 'question' exceeds {MAX_QUESTION_CHARS} characters.", True

    context = args.get("context")
    if context is not None and not isinstance(context, str):
        return "Error: 'context' must be a string.", True
    if context and len(context) > MAX_CONTEXT_CHARS:
        return f"Error: 'context' exceeds {MAX_CONTEXT_CHARS} characters.", True

    if get_api_key() is None:
        return "OPENROUTER_API_KEY is not set in the lifeline server's environment.", True

    name = args.get("friend")
    if name is None:
        name = default_friend_name(friends)
    if not isinstance(name, str) or name not in friends:
        return f"Unknown friend {name!r}. Available: {', '.join(friends)}.", True

    model = friends[name].get("model")
    if not isinstance(model, str) or not model:
        return f"Friend '{name}' has no valid model configured.", True

    prompt = question if not context else f"{question}\n\n--- Additional context ---\n{context}"

    try:
        answer, meta = call_openrouter(model, prompt)
    except urllib.error.HTTPError as e:
        try:
            detail = e.read(4096).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            detail = ""
        print(f"lifeline: OpenRouter HTTP {e.code} ({name}): {detail}", file=sys.stderr)
        return f"phone_a_friend error ({name}): OpenRouter returned HTTP {e.code}.", True
    except Exception as e:  # noqa: BLE001 — full detail to stderr, sanitized to client
        print(f"lifeline: phone_a_friend failed ({name}): {e!r}", file=sys.stderr)
        return f"phone_a_friend error ({name}): {type(e).__name__} (see server logs).", True

    return f"{answer}\n\n---\n_via {name} ({meta})_", False


# --- JSON-RPC plumbing -------------------------------------------------------

def send(msg):
    # allow_nan=False guarantees a valid JSON-RPC line (no NaN/Infinity); the lock
    # serializes writes from concurrent worker threads.
    try:
        line = json.dumps(msg, ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError) as e:
        line = json.dumps({"jsonrpc": "2.0", "id": None,
                           "error": {"code": INTERNAL_ERROR, "message": f"unserializable response: {e}"}})
    with _OUT_LOCK:
        _REAL_STDOUT.write(line + "\n")
        _REAL_STDOUT.flush()


def result(req_id, payload):
    send({"jsonrpc": "2.0", "id": req_id, "result": payload})


def error(req_id, code, message):
    send({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}})


def handle(msg, friends):
    method = msg.get("method")

    # A message with no "method" is a response/echo, not a request — ignore it.
    if not isinstance(method, str):
        return
    # No "id" key ⇒ notification: never reply (distinct from "id": null, a request).
    is_notification = "id" not in msg
    req_id = msg.get("id")

    if is_notification:
        return  # e.g. notifications/initialized, notifications/cancelled — no-op

    if method == "initialize":
        client_proto = (msg.get("params") or {}).get("protocolVersion")
        proto = client_proto if client_proto in SUPPORTED_PROTOCOLS else DEFAULT_PROTOCOL
        result(req_id, {
            "protocolVersion": proto,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        })
        return

    if method == "tools/list":
        result(req_id, {"tools": [build_tool_schema(friends)]})
        return

    if method == "tools/call":
        params = msg.get("params")
        if not isinstance(params, dict):
            error(req_id, INVALID_PARAMS, "params must be an object")
            return
        if params.get("name") != "phone_a_friend":
            error(req_id, INVALID_PARAMS, f"Unknown tool: {params.get('name')!r}")
            return
        arguments = params.get("arguments", {})
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            error(req_id, INVALID_PARAMS, "tool arguments must be an object")
            return
        text, is_error = run_phone_a_friend(arguments, friends)
        payload = {"content": [{"type": "text", "text": text}]}
        if is_error:
            payload["isError"] = True
        result(req_id, payload)
        return

    if method == "ping":
        result(req_id, {})
        return

    error(req_id, METHOD_NOT_FOUND, f"Method not found: {method}")


def handle_safe(msg, friends):
    try:
        handle(msg, friends)
    except Exception as e:  # noqa: BLE001 — a bad message must never kill a worker or re-raise
        print(f"lifeline: internal error handling message: {e!r}", file=sys.stderr)
        if isinstance(msg, dict) and "id" in msg:
            error(msg["id"], INTERNAL_ERROR, "Internal error (see server logs).")


def main():
    friends = load_friends()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            error(None, PARSE_ERROR, "Parse error")
            continue
        if isinstance(msg, list):
            error(None, INVALID_REQUEST, "Batch requests are not supported")
            continue
        if not isinstance(msg, dict):
            error(None, INVALID_REQUEST, "Invalid Request")
            continue
        # Dispatch on a daemon thread so a long phone_a_friend call doesn't block
        # the read loop from answering ping / accepting further messages.
        threading.Thread(target=handle_safe, args=(msg, friends), daemon=True).start()


if __name__ == "__main__":
    main()
