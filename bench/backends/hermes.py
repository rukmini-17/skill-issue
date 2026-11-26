"""Prompt-mode tool calling in Qwen3's own (hermes) format (``tool_mode: prompt``).

For servers that may not accept the ``tools`` field (Tinker), the client does
what Qwen3's chat template does when it renders tools:

* the tool schemas are appended to the system message inside ``<tools>``;
* an assistant message with tool calls becomes text with one
  ``<tool_call>{"name": .., "arguments": {..}}</tool_call>`` block per call;
* tool results become a ``user`` message holding ``<tool_response>`` blocks
  (consecutive results are merged into one message, as the template does).

The reply is parsed with ``bench.harness.model.parse_hermes_tool_calls``. The
wording below follows the Qwen3 chat template (``tokenizer_config.json``).
"""

from __future__ import annotations

import json

TOOLS_HEADER = (
    "# Tools\n\nYou may call one or more functions to assist with the user query.\n\n"
    "You are provided with function signatures within <tools></tools> XML tags:\n<tools>"
)
TOOLS_FOOTER = (
    "\n</tools>\n\nFor each function call, return a json object with function name and arguments "
    "within <tool_call></tool_call> XML tags:\n<tool_call>\n"
    '{"name": <function-name>, "arguments": <args-json-object>}\n</tool_call>'
)


def tools_block(tools: list[dict]) -> str:
    return TOOLS_HEADER + "".join("\n" + json.dumps(t, ensure_ascii=False) for t in tools) + TOOLS_FOOTER


def _call_text(call: dict) -> str:
    fn = call.get("function") or {}
    raw = fn.get("arguments") or "{}"
    try:
        args = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        args = raw                     # keep the model's own malformed text
    return "<tool_call>\n" + json.dumps({"name": fn.get("name", ""), "arguments": args},
                                        ensure_ascii=False) + "\n</tool_call>"


def to_prompt_messages(messages: list[dict], tools: list[dict] | None) -> list[dict]:
    """OpenAI messages with tool calls -> plain system/user/assistant messages."""
    out: list[dict] = []
    if tools:
        if messages and messages[0].get("role") == "system":
            out.append({"role": "system", "content": (messages[0].get("content") or "") + "\n\n" + tools_block(tools)})
            rest = messages[1:]
        else:
            out.append({"role": "system", "content": tools_block(tools)})
            rest = messages
    else:
        rest = messages
    for m in rest:
        role = m.get("role")
        if role == "assistant":
            parts = [m.get("content") or ""] + [_call_text(c) for c in m.get("tool_calls") or []]
            out.append({"role": "assistant", "content": "\n".join(p for p in parts if p)})
        elif role == "tool":
            block = "<tool_response>\n" + str(m.get("content") or "") + "\n</tool_response>"
            if out and out[-1].get("_tool_responses"):
                out[-1]["content"] += "\n" + block
            else:
                out.append({"role": "user", "content": block, "_tool_responses": True})
        else:
            out.append({"role": role, "content": m.get("content") or ""})
    for m in out:
        m.pop("_tool_responses", None)
    return out
