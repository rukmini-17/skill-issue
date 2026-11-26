"""Chat-model client for the agent loop (workstream B, B3).

The agent talks to any OpenAI-compatible chat endpoint with tool calling
(D11). ``ChatModel`` is the minimal interface the loop needs; the clients
(vllm / llamacpp / tinker / ollama) live in ``bench.backends``.
``OpenAIChatModel`` is an alias of ``bench.backends.base.OpenAICompatModel``.

Tool-call parsing per model family:

* Servers normally return structured ``tool_calls``. Those are used as given.
* ``qwen3`` (hermes format): when the server did not parse them (llama.cpp
  without ``--jinja``, or a parser miss), ``<tool_call>{"name": ..,
  "arguments": {..}}</tool_call>`` blocks in the content are parsed.
* Qwen3 ``<think>...</think>`` blocks are removed from the content kept in
  the conversation (Qwen's guidance for multi-turn use) and stored separately.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolCallRequest:
    id: str
    name: str
    arguments: str              # raw JSON text, as the model produced it


@dataclass
class AssistantTurn:
    content: str                # visible content (thinking removed)
    tool_calls: list[ToolCallRequest]
    reasoning: str = ""         # removed <think> text / server reasoning_content
    finish_reason: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
    seconds: float = 0.0
    parsed_from_content: bool = False   # tool calls recovered from text (family fallback)


class ChatModel(Protocol):
    name: str
    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> AssistantTurn: ...
    def describe(self) -> dict: ...      # backend, model file, quantization, decoding (meta.json)


_THINK = re.compile(r"<think>(.*?)</think>", re.S)
_HERMES = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.S)


def split_thinking(content: str) -> tuple[str, str]:
    thoughts = [m.strip() for m in _THINK.findall(content or "")]
    visible = _THINK.sub("", content or "")
    if "</think>" in visible:                 # opening tag in the chat template, not the output
        head, _, visible = visible.partition("</think>")
        thoughts.insert(0, head.strip())
    return visible.strip(), "\n".join(t for t in thoughts if t)


def parse_hermes_tool_calls(content: str) -> tuple[str, list[ToolCallRequest]]:
    """Qwen3/hermes ``<tool_call>`` blocks -> calls; returns the remaining text too.

    A block that is not JSON becomes a call named ``""`` with the raw text as
    arguments, so the loop reports it to the model as malformed.
    """
    calls: list[ToolCallRequest] = []
    for raw in _HERMES.findall(content or ""):
        cid = f"call_{uuid.uuid4().hex[:12]}"
        try:
            obj = json.loads(raw)
            name = obj.get("name", "") if isinstance(obj, dict) else ""
            args = obj.get("arguments", {}) if isinstance(obj, dict) else {}
            calls.append(ToolCallRequest(cid, str(name),
                                         args if isinstance(args, str) else json.dumps(args)))
        except json.JSONDecodeError:
            calls.append(ToolCallRequest(cid, "", raw))
    return _HERMES.sub("", content or "").strip(), calls


def normalise_turn(content: str | None, tool_calls: list[ToolCallRequest], family: str,
                   reasoning: str = "") -> AssistantTurn:
    visible, thought = split_thinking(content or "")
    reasoning = "\n".join(x for x in (reasoning, thought) if x)
    parsed = False
    if not tool_calls and family == "qwen3" and "<tool_call>" in visible:
        visible, tool_calls = parse_hermes_tool_calls(visible)
        parsed = True
    return AssistantTurn(visible, tool_calls, reasoning, parsed_from_content=parsed)


def __getattr__(name):
    # The OpenAI-compatible client moved to bench.backends (B5); kept here for old imports.
    if name == "OpenAIChatModel":
        from bench.backends.base import OpenAICompatModel
        return OpenAICompatModel
    raise AttributeError(name)


class ScriptedModel:
    """Test double: returns pre-written turns in order, then a final text answer.

    Each script entry is either a string (final answer, no tool calls), a list of
    ``(tool_name, args_dict_or_raw_str)`` pairs, or a callable
    ``(messages) -> entry`` for turns that depend on earlier tool results.
    """

    def __init__(self, script: list, name: str = "scripted", family: str = "qwen3"):
        self.name = name
        self.family = family
        self.script = list(script)
        self.calls: list[list[dict]] = []

    def describe(self) -> dict:
        return {"name": self.name, "backend": "scripted", "model": self.name, "model_file": None,
                "quantization": None, "family": self.family, "decoding": {}}

    def chat(self, messages: list[dict], tools: list[dict]) -> AssistantTurn:
        self.calls.append(json.loads(json.dumps(messages)))
        entry = self.script.pop(0) if self.script else "done"
        if callable(entry):
            entry = entry(messages)
        if isinstance(entry, str):
            return normalise_turn(entry, [], self.family)
        calls = []
        for name, args in entry:
            calls.append(ToolCallRequest(f"call_{uuid.uuid4().hex[:12]}", name,
                                         args if isinstance(args, str) else json.dumps(args)))
        return AssistantTurn("", calls)
