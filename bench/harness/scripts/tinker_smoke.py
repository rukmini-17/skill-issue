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

``--pilot-request`` sends instead the harness's real first request for a task (system prompt
with the repo's skill list, the explicit-v2 task prompt, all five tool schemas, setup d9's
max_tokens 8192, seed 0 as for r0) and prints the server's full error body. If it is
rejected, it sends variants with one field removed (``bench.harness.request_probe``; all at
max_tokens 16) and stops at the first that is accepted: that field is the culprit.
Rejected requests cost nothing; an accepted one about $0.002. Hard cap ``--max-cost-usd``
(default $0.02):

    .venv/bin/python bench/harness/scripts/tinker_smoke.py --model qwen3.6-35b-a3b-tinker --pilot-request
        [--task ops-office-t05] [--invocation explicit] [--setup d9] [--seed 0] [--all]
        [--dump runs/tinker/pilot_request.json]
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
    ap.add_argument("--pilot-request", action="store_true",
                    help="send the harness's first pilot request, then one-field-removed variants")
    ap.add_argument("--task", default="ops-office-t05")
    ap.add_argument("--invocation", choices=("natural", "explicit"), default="explicit")
    ap.add_argument("--setup", default="d9")
    ap.add_argument("--seed", type=int, default=0, help="the pilot sends the repeat number (r0 = 0)")
    ap.add_argument("--all", action="store_true", help="try every variant, not only up to the first accepted")
    ap.add_argument("--max-cost-usd", type=float, default=0.02, help="hard cap for --pilot-request")
    ap.add_argument("--dump", type=Path, help="write the exact request JSON here (no key in it)")
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
    if a.pilot_request:
        return probe(entry, overrides, a)
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


def _send(m, kw: dict) -> dict:
    """One raw request; the outcome without prompt texts. Never retried."""
    from bench.backends.base import classify
    try:
        r = m._client.chat.completions.create(**kw)
    except Exception as e:
        err = m._redact(classify(e))
        return {"accepted": False, "status": err.status, "kind": err.kind, "error": str(err)[:600],
                "body": err.body}
    ch = r.choices[0]
    usage = {"prompt_tokens": r.usage.prompt_tokens, "completion_tokens": r.usage.completion_tokens} if r.usage else {}
    return {"accepted": True, "finish_reason": ch.finish_reason, "usage": usage,
            "tool_calls": [c.function.name for c in (ch.message.tool_calls or [])],
            "cost_usd": cost_usd(usage, m.price)}


def probe(entry: str, overrides: dict, a) -> int:
    from bench.harness.request_probe import pilot_request, shape, variants
    m = make_model(entry, seed=a.seed, retries=0, timeout=180, **overrides)
    kw = pilot_request(m, a.task, a.invocation, a.setup)
    print(f"pilot request for {m.model} ({a.task}, {a.invocation}, setup {a.setup}, seed {a.seed}):")
    print(json.dumps(shape(kw), indent=1))
    if a.dump:
        a.dump.parent.mkdir(parents=True, exist_ok=True)
        a.dump.write_text(json.dumps(kw, indent=1))
        print(f"request written to {a.dump}")
    spent, found = 0.0, None
    for name, v in variants(kw):
        worst = m.worst_turn_cost(v)
        if spent + worst > a.max_cost_usd:
            print(f"-- {name}: skipped (could pass the ${a.max_cost_usd:.2f} cap)")
            continue
        out = _send(m, v)
        spent += out.get("cost_usd") or 0.0
        print(f"-- {name}: " + json.dumps(out, indent=1, default=str))
        if out["accepted"]:
            if name == "exact":
                print("exact pilot request ACCEPTED: the 422 did not reproduce (check model, task, seed)")
                break
            found = found or name
            if not a.all:
                break
    print(f"\nspent about ${spent:.4f}")
    if found:
        print(f"first accepted variant: '{found}' -> that change makes the request valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
