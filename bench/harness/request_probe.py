"""Rebuild the harness's first model request for a task, and variants of it with one thing
removed, to find which field a server rejects (``tinker_smoke.py --pilot-request``).

The first request is exactly what ``Harness.run`` sends at step 1: the system prompt (D8 skill
list of the task's repo at v1), the user prompt (explicit-v2 prefix when asked), the five
tool schemas, and the model entry's decoding under the chosen setup (d9: max_tokens 8192) and
seed (the pilot passes the repeat number; r0 = 0). No sandbox is built: the skill list only
needs each SKILL.md's frontmatter, read from the repo's skill snapshot.

``variants(kw)`` yields ``(name, request)`` pairs:
* ``exact``: the request as the harness sends it;
* ``max_tokens=16``: the same with a tiny budget (also makes every later variant cheap);
* then, on top of ``max_tokens=16``, one change each: drop ``seed`` / ``parallel_tool_calls`` /
  ``tool_choice`` / ``temperature`` / ``top_p`` / ``extra_body`` (and each key of it), drop one
  tool, drop ``http_request.headers``, strip ``additionalProperties`` from all schemas, a short
  system prompt, no system message, and the smoke test's single ``get_time`` tool.
"""

from __future__ import annotations

import copy
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, Iterator

from bench.harness import agent as agent_mod
from bench.harness.run import REPOS
from bench.harness.skills import repo_install_set
from bench.harness.tools import TOOL_SCHEMAS

GET_TIME = [{"type": "function", "function": {
    "name": "get_time", "description": "Return the current UTC time.",
    "parameters": {"type": "object", "properties": {}, "required": []}}}]


def first_messages(task_id: str, invocation: str = "explicit") -> list[dict]:
    repo_id = task_id.rsplit("-t", 1)[0]
    from bench.common.data import load_repo
    task = load_repo(repo_id).tasks[task_id]
    installed = repo_install_set(REPOS / repo_id)
    ws = Path(tempfile.mkdtemp(prefix="cdb-probe-"))
    try:
        for sid, v in installed.items():
            dst = ws / ".github" / "skills" / sid
            dst.mkdir(parents=True)
            shutil.copy2(Path(v.root) / "SKILL.md", dst / "SKILL.md")
        system = agent_mod.system_prompt(ws, installed, agent_mod.load_template())
    finally:
        shutil.rmtree(ws, ignore_errors=True)
    user = agent_mod.user_prompt(task.prompt, task.skill_id, invocation)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def pilot_request(model, task_id: str, invocation: str = "explicit", setup: str = "d9") -> dict[str, Any]:
    """The harness's step-1 request for ``model`` (an OpenAICompatModel; its seed already set)."""
    mt = agent_mod.SETUPS[setup]["max_tokens"]
    if mt:
        model.max_tokens = mt
    return model.build_request(first_messages(task_id, invocation), TOOL_SCHEMAS)


def _strip_additional(obj):
    if isinstance(obj, dict):
        return {k: _strip_additional(v) for k, v in obj.items() if k != "additionalProperties"}
    if isinstance(obj, list):
        return [_strip_additional(v) for v in obj]
    return obj


def variants(kw: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    yield "exact", kw
    small = copy.deepcopy(kw)
    small["max_tokens"] = 16
    yield "max_tokens=16", small

    def drop(field):
        k = copy.deepcopy(small)
        k.pop(field, None)
        return k

    for f in ("seed", "parallel_tool_calls", "tool_choice", "temperature", "top_p"):
        if f in small:
            yield f"no {f}", drop(f)
    if "extra_body" in small:
        yield "no extra_body", drop("extra_body")
        for key in small["extra_body"]:
            k = copy.deepcopy(small)
            k["extra_body"].pop(key)
            if not k["extra_body"]:
                k.pop("extra_body")
            yield f"no extra_body.{key}", k
    tools = small.get("tools") or []
    for t in tools:
        k = copy.deepcopy(small)
        k["tools"] = [x for x in tools if x["function"]["name"] != t["function"]["name"]]
        yield f"no tool {t['function']['name']}", k
    if any(t["function"]["name"] == "http_request" for t in tools):
        k = copy.deepcopy(small)
        for t in k["tools"]:
            if t["function"]["name"] == "http_request":
                t["function"]["parameters"]["properties"].pop("headers", None)
        yield "http_request without headers", k
    if "additionalProperties" in json.dumps(tools):
        k = copy.deepcopy(small)
        k["tools"] = _strip_additional(k["tools"])
        yield "no additionalProperties in schemas", k
    msgs = small.get("messages") or []
    if msgs and msgs[0].get("role") == "system":
        k = copy.deepcopy(small)
        k["messages"][0]["content"] = "You are a coding agent. Use the tools to complete the task."
        yield "short system prompt", k
        k = copy.deepcopy(small)
        k["messages"] = k["messages"][1:]
        yield "no system message", k
    if tools:
        k = copy.deepcopy(small)
        k["tools"] = GET_TIME
        yield "smoke tool only (get_time)", k


def shape(kw: dict[str, Any]) -> dict[str, Any]:
    """What the request contains, without the prompt texts (for the terminal)."""
    msgs = kw.get("messages") or []
    return {"fields": sorted(kw), "model": kw.get("model"), "max_tokens": kw.get("max_tokens"),
            "seed": kw.get("seed"), "temperature": kw.get("temperature"),
            "parallel_tool_calls": kw.get("parallel_tool_calls"), "tool_choice": kw.get("tool_choice"),
            "extra_body": kw.get("extra_body"),
            "messages": [{"role": m.get("role"), "chars": len(m.get("content") or "")} for m in msgs],
            "tools": [t["function"]["name"] for t in kw.get("tools") or []],
            "request_json_chars": len(json.dumps(kw))}
