"""Agent loop (workstream B, B3).

``run_agent`` drives one model through one task:

* messages = system prompt (D8 skill list) + the task prompt (``/<skill_id> ``
  prefixed for ``invocation: explicit``);
* each model turn may call tools; each call goes through ``ToolExecutor``;
* malformed calls (unknown tool, bad JSON, wrong arguments) are returned to the
  model as errors and logged (``AgentResult.malformed``); they are not executed
  and get no tool line;
* stop when a turn has no tool call (``done``), at ``max_steps`` model turns
  (``step_limit``), at the wall-clock budget (``timeout``) or on a model or
  harness error (``error``). ``run_end`` is written in every case.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from bench.harness.model import ChatModel
from bench.harness.skills import skill_frontmatter
from bench.harness.tools import TOOL_SCHEMAS, MalformedCall, ToolExecutor, parse_call

PROMPT_PATH = Path(__file__).with_name("prompts") / "system.md"
MAX_STEPS = 25                  # D11
RUN_TIMEOUT = 1800.0            # seconds of wall clock per agent run (B; revisit after the pilot)


def load_template(path: Path = PROMPT_PATH) -> str:
    text = path.read_text(encoding="utf-8")
    marker = "---8<---\n-->\n"
    return text.split(marker, 1)[1] if marker in text else text


def skill_lines(workspace: Path, installed: dict) -> str:
    lines = []
    for sid in sorted(installed):
        rel = f".github/skills/{sid}/SKILL.md"
        fm = skill_frontmatter(workspace / rel)
        name = str(fm.get("name") or sid)
        desc = " ".join(str(fm.get("description") or "").split())
        lines.append(f"- {name}: {desc} (path: `{rel}`)")
    return "\n".join(lines)


def system_prompt(workspace: Path, installed: dict, template: str | None = None) -> str:
    return (template or load_template()).replace("{skills}", skill_lines(workspace, installed))


def user_prompt(task_prompt: str, skill_id: str, invocation: str) -> str:
    return f"/{skill_id} {task_prompt}" if invocation == "explicit" else task_prompt


@dataclass
class AgentResult:
    reason: str                       # done | step_limit | timeout | error
    steps: int                        # model turns
    tool_calls: int = 0
    malformed: list[dict] = field(default_factory=list)
    error: str | None = None
    error_kind: str | None = None     # BackendError.kind (connection, context_length, ...)
    truncated_turns: int = 0          # finish_reason == "length"
    final_text: str = ""
    model_seconds: float = 0.0
    usage: dict[str, int] = field(default_factory=dict)
    messages: list[dict] = field(default_factory=list)
    turns: list[dict] = field(default_factory=list)       # per model turn (meta.json "turns")
    reasoning: list[dict] = field(default_factory=list)   # {"step", "text"} -> reasoning.json
    skipped_calls: int = 0                                # one_call_per_turn: calls not run

    def behaviour(self) -> dict:
        """Run-level counts from ``turns`` (meta.json; pilot "behaviour" table)."""
        t = self.turns
        return {"multi_call_turns": sum(len(x["tool_calls"]) > 1 for x in t),
                "blind_write_turns": sum(x["blind_write"] for x in t),
                "turns_with_reasoning": sum(x["reasoning_chars"] > 0 for x in t),
                "reasoning_chars": sum(x["reasoning_chars"] for x in t),
                "skipped_calls": self.skipped_calls}


# A write composed in the same turn as calls whose results the model has not seen yet.
_LOOK = {"read_file", "list_dir", "http_request", "run_command"}
SKIPPED_NOTE = ("not run: this harness runs one tool call per turn, so only your first call was "
                "executed. Look at its result, then make this call again if you still need it.")


def turn_record(step: int, turn) -> dict:
    names = [c.name for c in turn.tool_calls]
    return {"step": step, "tool_calls": names, "finish_reason": turn.finish_reason,
            "completion_tokens": turn.usage.get("completion_tokens"),
            "content_chars": len(turn.content or ""), "reasoning_chars": len(turn.reasoning or ""),
            "parsed_from_content": turn.parsed_from_content,
            "blind_write": "write_file" in names and bool(_LOOK & set(names))}


def run_agent(model: ChatModel, executor: ToolExecutor, system: str, user: str,
              max_steps: int = MAX_STEPS, timeout: float = RUN_TIMEOUT,
              one_call_per_turn: bool = False) -> AgentResult:
    """``one_call_per_turn`` (PROPOSED, off by default; NOTES.md open decision): run only
    the first tool call of a turn and answer the others with ``SKIPPED_NOTE``, so the
    model sees each result before acting on it."""
    t0 = time.monotonic()
    messages: list[dict] = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    res = AgentResult("done", 0, messages=messages)
    usage = {"prompt_tokens": 0, "completion_tokens": 0}
    try:
        while True:
            if res.steps >= max_steps:
                res.reason = "step_limit"
                break
            if time.monotonic() - t0 > timeout:
                res.reason = "timeout"
                break
            turn = model.chat(messages, TOOL_SCHEMAS)
            res.steps += 1
            res.model_seconds += turn.seconds
            if turn.finish_reason == "length":
                res.truncated_turns += 1
            for k in usage:
                usage[k] += turn.usage.get(k, 0)
            res.turns.append(turn_record(res.steps, turn))
            if turn.reasoning:
                res.reasoning.append({"step": res.steps, "text": turn.reasoning})
            msg: dict = {"role": "assistant", "content": turn.content}
            if turn.tool_calls:
                msg["tool_calls"] = [{"id": c.id, "type": "function",
                                      "function": {"name": c.name, "arguments": c.arguments}}
                                     for c in turn.tool_calls]
            messages.append(msg)
            if not turn.tool_calls:
                res.final_text = turn.content
                res.reason = "done"
                break
            for i, c in enumerate(turn.tool_calls):
                if one_call_per_turn and i > 0:
                    res.skipped_calls += 1
                    messages.append({"role": "tool", "tool_call_id": c.id, "content": SKIPPED_NOTE})
                    continue
                try:
                    args = parse_call(c.name, c.arguments)
                except MalformedCall as e:
                    res.malformed.append({"step": res.steps, "name": c.name, "arguments": c.arguments[:2000],
                                          "error": str(e), "parsed_from_content": turn.parsed_from_content})
                    messages.append({"role": "tool", "tool_call_id": c.id,
                                     "content": f"error: malformed tool call: {e}"})
                    continue
                out = executor.execute(c.name, args)
                res.tool_calls += 1
                messages.append({"role": "tool", "tool_call_id": c.id, "content": out.text})
                if time.monotonic() - t0 > timeout:
                    break
    except Exception as e:                                    # model/server failure: record, don't crash
        res.reason = "error"
        res.error = f"{type(e).__name__}: {e}"
        res.error_kind = getattr(e, "kind", None)
    res.usage = usage
    executor.trace.event("run_end", reason=res.reason, steps=res.steps)
    return res


def dump_messages(messages: list[dict], path: Path) -> None:
    path.write_text(json.dumps(messages, indent=1, ensure_ascii=False), encoding="utf-8")
