"""One Tinker call to check a model through the OpenAI-compatible endpoint (HUMANS RUN THIS;
it spends credit: at most 1024 sampled tokens, under $0.01 on every entry).

    . ~/.tinker_key        # export TINKER_API_KEY=... (never in the repo)
    .venv/bin/python bench/harness/scripts/tinker_smoke.py                                  # qwen3-8b-tinker
    .venv/bin/python bench/harness/scripts/tinker_smoke.py --model qwen3.6-35b-a3b-tinker   # models.yaml entry
    .venv/bin/python bench/harness/scripts/tinker_smoke.py --model Qwen/Qwen3.8-27B         # raw base-model ID

Sends ONE /chat/completions request built by the harness's own backend
(``build_request``: native tools, ``parallel_tool_calls: false``, the entry's decoding), with
one trivial tool (``get_time``) and max_tokens=1024 (thinking stays on, as in the pilot;
``--no-think`` appends ``/no_think``), so it tests the exact request shape the pilot sends. It answers:

1. Does the endpoint accept the model ID and ``tools`` (or reject them with a 4xx)?
2. Does it return structured ``tool_calls`` (tool_mode native works) or only text?

Prints the HTTP outcome, finish_reason, the tool calls, a short text snippet, token usage and
the cost at the entry's ``price`` (prefill + sampled). The key is read from the environment
and never printed; error texts are redacted.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # repo root, for bench.*

from bench.backends import load_models, make_model, model_config
from bench.backends.base import cost_usd

MAX_TOKENS = 1024
TOOLS = [{"type": "function", "function": {
    "name": "get_time", "description": "Return the current UTC time.",
    "parameters": {"type": "object", "properties": {}, "required": []}}}]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen3-8b-tinker",
                    help="a tinker entry in models.yaml, or a raw base-model ID like Qwen/Qwen3.8-27B "
                         "(then qwen3-8b-tinker's settings with that ID, and no price)")
    ap.add_argument("--tool-mode", choices=("native", "prompt"), default=None,
                    help="override the entry's tool_mode (default: the entry's)")
    ap.add_argument("--max-tokens", type=int, default=MAX_TOKENS)
    ap.add_argument("--no-think", action="store_true", help="append /no_think to the prompt")
    a = ap.parse_args(argv)
    entry, overrides = a.model, {}
    if a.model not in load_models():
        entry, overrides = "qwen3-8b-tinker", {"model": a.model, "price": None}
    if model_config(entry).get("backend") != "tinker":
        print(f"{a.model} is not a tinker entry")
        return 2
    if not os.environ.get(model_config(entry).get("api_key_env", "TINKER_API_KEY")):
        print("TINKER_API_KEY is not set (. ~/.tinker_key first)")
        return 2
    if a.tool_mode:
        overrides["tool_mode"] = a.tool_mode
    m = make_model(entry, max_tokens=a.max_tokens, retries=0, timeout=180, **overrides)
    msgs = [{"role": "user", "content": "What time is it in UTC? Call the get_time tool."
             + (" /no_think" if a.no_think else "")}]
    kw = m.build_request(msgs, TOOLS)
    print(f"POST {m.base_url}/chat/completions model={m.model} tool_mode={m.tool_mode} "
          f"max_tokens={a.max_tokens} tools=[get_time] parallel_tool_calls={kw.get('parallel_tool_calls')}")
    try:
        turn = m.chat(msgs, TOOLS)
    except Exception as e:                          # the error itself answers question 1
        print(json.dumps({"accepted": False, "kind": getattr(e, "kind", None),
                          "status": getattr(e, "status", None), "error": str(e)[:600]}, indent=1))
        return 1
    calls = [{"name": c.name, "arguments": c.arguments} for c in turn.tool_calls]
    cost = cost_usd(turn.usage, m.price)
    out = {
        "accepted": True, "model": m.model, "finish_reason": turn.finish_reason, "tool_calls": calls,
        "structured_tool_calls": bool(calls) and not turn.parsed_from_content,
        "text_snippet": (turn.content or "")[:300], "reasoning_chars": len(turn.reasoning or ""),
        "usage": turn.usage, "seconds": round(turn.seconds, 2),
        "cost_usd": None if cost is None else round(cost, 6),
        "price_per_m": m.price,
        "verdict": ("native tool_calls returned: tool_mode native works" if calls and not turn.parsed_from_content
                    else "tool call only parsed from text: use tool_mode prompt" if calls
                    else "no tool call: check finish_reason / try --tool-mode prompt"),
    }
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
