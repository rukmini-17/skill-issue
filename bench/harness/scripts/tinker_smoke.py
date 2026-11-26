"""One Tinker call to check the OpenAI-compatible endpoint (HUMANS RUN THIS; it spends credit).

    TINKER_API_KEY=... .venv/bin/python bench/harness/scripts/tinker_smoke.py

Sends ONE /chat/completions request to qwen3-8b-tinker (Qwen/Qwen3-8B) with one
trivial tool (`get_time`) and max_tokens=200: at $0.60 per million sampled tokens
that is at most about $0.0001. It answers two questions:

1. Does the endpoint accept `tools` at all (or reject them with a 4xx)?
2. If accepted, does it return structured `tool_calls` (then tool_mode: native
   could work) or only `<tool_call>` text (keep tool_mode: prompt)?

Prints the HTTP outcome, finish_reason, whether tool_calls came back, a short
snippet of the text, and the token usage. The key is read from the environment
and never printed.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # repo root, for bench.*

from openai import OpenAI

from bench.backends import model_config

MAX_TOKENS = 200
PRICE_PER_M = 0.60


def main() -> int:
    cfg = model_config("qwen3-8b-tinker")
    key = os.environ.get(cfg.get("api_key_env", "TINKER_API_KEY"))
    if not key:
        print("set TINKER_API_KEY first")
        return 2
    client = OpenAI(base_url=cfg["base_url"], api_key=key, max_retries=0, timeout=120)
    tools = [{"type": "function", "function": {
        "name": "get_time", "description": "Return the current UTC time.",
        "parameters": {"type": "object", "properties": {}, "required": []}}}]
    print(f"POST {cfg['base_url']}/chat/completions model={cfg['model']} max_tokens={MAX_TOKENS} tools=[get_time]")
    try:
        r = client.chat.completions.create(
            model=cfg["model"], max_tokens=MAX_TOKENS, temperature=0, tools=tools,
            messages=[{"role": "user", "content": "What time is it in UTC? Call the get_time tool. /no_think"}])
    except Exception as e:                          # the error itself answers question 1
        status = getattr(e, "status_code", None)
        body = getattr(getattr(e, "response", None), "text", "") or str(e)
        print(json.dumps({"accepted": False, "status": status, "error": type(e).__name__,
                          "body": body[:600]}, indent=1))
        return 1
    ch = r.choices[0]
    msg = ch.message
    calls = [{"name": c.function.name, "arguments": c.function.arguments} for c in (msg.tool_calls or [])]
    text = msg.content or ""
    u = r.usage
    out = {
        "accepted": True, "finish_reason": ch.finish_reason, "tool_calls": calls,
        "text_has_<tool_call>": "<tool_call>" in text, "text_snippet": text[:300],
        "usage": u.model_dump() if u else None,
        "est_cost_usd": round((u.completion_tokens if u else MAX_TOKENS) * PRICE_PER_M / 1e6, 6),
        "verdict": ("native tool_calls returned: tool_mode native may work" if calls else
                    "no structured tool_calls: keep tool_mode prompt"),
    }
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
