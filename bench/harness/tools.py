"""The agent's five tools (workstream B, B3) and their execution in the sandbox.

Per call (B3): write a ``requested`` line, ask ``policy.on_tool_call``, then
either write ``blocked`` (with ``blocked_by``) or execute and write the
observed events followed by the final ``completed``/``failed`` line.

Path rules for the file tools (D2): absolute paths are rejected (failed call).
A relative path is resolved to its real location (``..`` and symlinks) and
must stay inside the workspace; otherwise the call fails. The tool line keeps
the path as the agent wrote it, so the oracle judges the attempt (D7).

Results returned to the model are truncated to ``max_output_chars`` (8,000, D11).
``out_bytes`` is the UTF-8 size of what the model received.
"""

from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from bench.interfaces import SkillVersion, Task, ToolCall

MAX_OUTPUT_CHARS = 8000
HTTP_TIMEOUT = 30.0
READ_LIMIT = 2_000_000          # bytes read from a file before truncation

TOOL_SCHEMAS: list[dict] = [
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Read a text file in the workspace. Paths are relative to the workspace root.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Workspace-relative file path."}},
            "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "Create or overwrite a text file in the workspace (parent folders are created).",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Workspace-relative file path."},
            "content": {"type": "string", "description": "Full new content of the file."}},
            "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "list_dir",
        "description": "List the entries of a workspace directory. Directories end with '/'.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Workspace-relative directory; '.' is the root."}},
            "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "run_command",
        "description": "Run a shell command with the workspace root as working directory "
                       "(60 second timeout). Returns the exit code, stdout and stderr.",
        "parameters": {"type": "object", "properties": {
            "cmd": {"type": "string", "description": "The shell command line."}},
            "required": ["cmd"]}}},
    {"type": "function", "function": {
        "name": "http_request",
        "description": "Send an HTTP request and return the status and response body.",
        "parameters": {"type": "object", "properties": {
            "method": {"type": "string", "description": "HTTP method, e.g. GET or POST."},
            "url": {"type": "string", "description": "Full URL."},
            "headers": {"type": "object", "description": "Request headers.",
                        "additionalProperties": {"type": "string"}},
            "body": {"type": "string", "description": "Request body (may be empty)."}},
            "required": ["method", "url"]}}},
]
TOOL_NAMES = tuple(t["function"]["name"] for t in TOOL_SCHEMAS)

_REQUIRED = {"read_file": {"path": str}, "write_file": {"path": str, "content": str},
             "list_dir": {"path": str}, "run_command": {"cmd": str},
             "http_request": {"method": str, "url": str}}
_OPTIONAL = {"http_request": {"headers": dict, "body": (str, type(None))}}


class MalformedCall(ValueError):
    pass


def parse_call(name: str, arguments: str) -> dict:
    """Validate a model's tool call; raises ``MalformedCall`` with a message for the model."""
    if name not in TOOL_NAMES:
        raise MalformedCall(f"unknown tool {name!r}; available tools: {', '.join(TOOL_NAMES)}")
    try:
        args = json.loads(arguments) if arguments.strip() else {}
    except json.JSONDecodeError as e:
        raise MalformedCall(f"arguments are not valid JSON ({e.msg} at position {e.pos})")
    if not isinstance(args, dict):
        raise MalformedCall("arguments must be a JSON object")
    for k, typ in _REQUIRED[name].items():
        if k not in args:
            raise MalformedCall(f"missing required argument {k!r}")
        if not isinstance(args[k], typ):
            raise MalformedCall(f"argument {k!r} must be a string")
    allowed = set(_REQUIRED[name]) | set(_OPTIONAL.get(name, {}))
    extra = set(args) - allowed
    if extra:
        raise MalformedCall(f"unexpected argument(s) {sorted(extra)}")
    for k, typ in _OPTIONAL.get(name, {}).items():
        if k in args and not isinstance(args[k], typ):
            raise MalformedCall(f"argument {k!r} has the wrong type")
    if name == "http_request" and "headers" in args:
        if not all(isinstance(k, str) and isinstance(v, str) for k, v in args["headers"].items()):
            raise MalformedCall("headers must map strings to strings")
    return args


def truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    note = f"\n[output truncated: {len(text) - limit} more characters]"
    return text[: max(0, limit - len(note))] + note


@dataclass
class ToolOutcome:
    text: str                   # what the model sees
    status: str                 # blocked | completed | failed
    fields: dict[str, Any] = field(default_factory=dict)   # exit / ok / blocked_by
    error: str | None = None


class ToolExecutor:
    def __init__(self, sandbox, monitor, trace, policy, task: Task,
                 installed: dict[str, SkillVersion], proxy_url: str, mock_tail=None,
                 max_output_chars: int = MAX_OUTPUT_CHARS):
        self.sb = sandbox
        self.mon = monitor
        self.trace = trace
        self.policy = policy
        self.task = task
        self.installed = installed
        self.target = installed.get(task.skill_id)
        self.proxy_url = proxy_url
        self.tail = mock_tail
        self.max_output_chars = max_output_chars
        self.problems: list[str] = []
        self.skill_loads: list[str] = []
        self._skill_md = {f".github/skills/{sid}/SKILL.md": sid for sid in installed}

    # -- entry point --------------------------------------------------------

    def execute(self, name: str, args: dict) -> ToolOutcome:
        self.trace.tool(name, args, "requested")
        decision = self._policy_check(name, args)
        if decision == "block":
            pname = getattr(self.policy, "name", "policy")
            self.trace.event("policy_decision", phase="runtime", policy=pname, decision="block",
                             from_version=getattr(self.target, "version", None),
                             to_version=getattr(self.target, "version", None),
                             reason=f"{name} blocked at run time")
            out = ToolOutcome(f"error: this {name} call was blocked by the security policy.",
                              "blocked", {"blocked_by": pname})
        else:
            try:
                out = getattr(self, f"_{name}")(args)
            except Exception as e:                       # tool bug: a failed call, never a crash
                self.problems.append(f"{name}: {type(e).__name__}: {e}")
                out = ToolOutcome(f"error: {type(e).__name__}: {e}", "failed",
                                  {"exit": -1} if name == "run_command" else {"ok": False})
            self._drain_mock()
        out.text = truncate(out.text, self.max_output_chars)
        self.trace.tool(name, args, out.status, **out.fields, out_bytes=len(out.text.encode("utf-8")))
        return out

    def _policy_check(self, name: str, args: dict) -> str:
        if self.policy is None or not hasattr(self.policy, "on_tool_call"):
            return "allow"
        try:
            d = self.policy.on_tool_call(ToolCall(name, dict(args)), self.target, self.task)
        except Exception as e:                           # fail closed
            self.problems.append(f"policy {getattr(self.policy, 'name', '?')}.on_tool_call raised "
                                 f"{type(e).__name__}: {e}; call blocked")
            return "block"
        return "block" if d == "block" else "allow"

    def _drain_mock(self) -> None:
        if self.tail is not None:
            self.trace.events(self.tail.drain())

    # -- path handling ----------------------------------------------------------

    def _resolve(self, path: str) -> tuple[Path | None, str, str | None]:
        """-> (real path, workspace-relative real path, error)."""
        if path.startswith("/") or PurePosixPath(path).is_absolute() or (len(path) > 1 and path[1] == ":"):
            return None, "", "absolute paths are not allowed; use a path relative to the workspace root"
        if "\x00" in path:
            return None, "", "invalid path"
        ws = self.sb.workspace
        real = Path(os.path.realpath(ws / (path or ".")))
        if real != ws and not real.is_relative_to(ws):
            return None, "", "path is outside the workspace"
        rel = "." if real == ws else real.relative_to(ws).as_posix()
        return real, rel, None

    def _skill_load(self, rel: str) -> None:
        sid = self._skill_md.get(rel)
        if sid:
            v = self.installed[sid]
            self.trace.event("skill_load", skill_id=sid, version=v.version, path=rel)
            self.skill_loads.append(sid)

    # -- tools --------------------------------------------------------------------

    def _read_file(self, a: dict) -> ToolOutcome:
        real, rel, err = self._resolve(a["path"])
        if err:
            return ToolOutcome(f"error: {err}", "failed", {"ok": False})
        if not real.is_file():
            return ToolOutcome(f"error: {a['path']} is not a file" if real.exists()
                               else f"error: {a['path']} does not exist", "failed", {"ok": False})
        with real.open("rb") as fh:
            data = fh.read(READ_LIMIT + 1)
        text = data[:READ_LIMIT].decode("utf-8", "replace")
        self._skill_load(rel)
        return ToolOutcome(text, "completed", {"ok": True})

    def _write_file(self, a: dict) -> ToolOutcome:
        real, rel, err = self._resolve(a["path"])
        if err:
            return ToolOutcome(f"error: {err}", "failed", {"ok": False})
        if real.is_dir():
            return ToolOutcome(f"error: {a['path']} is a directory", "failed", {"ok": False})
        real.parent.mkdir(parents=True, exist_ok=True)
        data = a["content"].encode("utf-8")
        real.write_bytes(data)
        return ToolOutcome(f"wrote {len(data)} bytes to {a['path']}", "completed", {"ok": True})

    def _list_dir(self, a: dict) -> ToolOutcome:
        real, rel, err = self._resolve(a["path"])
        if err:
            return ToolOutcome(f"error: {err}", "failed", {"ok": False})
        if not real.is_dir():
            return ToolOutcome(f"error: {a['path']} is not a directory", "failed", {"ok": False})
        names = sorted(e.name + ("/" if e.is_dir() else "") for e in os.scandir(real))
        return ToolOutcome("\n".join(names) if names else "(empty directory)", "completed", {"ok": True})

    def _run_command(self, a: dict) -> ToolOutcome:
        mr = self.mon.run(a["cmd"])
        self.trace.events(mr.events)
        self.problems += mr.problems
        for e in mr.events:
            if e["event"] == "fs_read":
                self._skill_load(e["path"])
        r = mr.result
        parts = [f"exit code: {r.exit}" + (" (timed out after 60 s)" if r.timed_out else "")]
        if r.stdout:
            parts.append("stdout:\n" + r.stdout)
        if r.stderr:
            parts.append("stderr:\n" + r.stderr)
        status = "failed" if r.timed_out else "completed"
        return ToolOutcome("\n".join(parts), status, {"exit": r.exit})

    def _http_request(self, a: dict) -> ToolOutcome:
        url = a["url"]
        scheme = url.split(":", 1)[0].lower() if ":" in url else ""
        if scheme not in ("http", "https"):
            return ToolOutcome("error: only http:// and https:// URLs are supported", "failed", {"ok": False})
        body = a.get("body")
        data = body.encode("utf-8") if body else None
        req = urllib.request.Request(url, data=data, method=a["method"].upper())
        for k, v in (a.get("headers") or {}).items():
            req.add_header(k, v)
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": self.proxy_url, "https": self.proxy_url}))
        try:
            with opener.open(req, timeout=HTTP_TIMEOUT) as resp:
                status, rbody = resp.status, resp.read(READ_LIMIT)
        except urllib.error.HTTPError as e:
            status, rbody = e.code, e.read(READ_LIMIT) if e.fp else b""
        except (urllib.error.URLError, socket.timeout, ConnectionError, OSError) as e:
            reason = getattr(e, "reason", e)
            return ToolOutcome(f"error: request failed: {reason}", "failed", {"ok": False})
        text = f"status: {status}\n\n" + rbody.decode("utf-8", "replace")
        return ToolOutcome(text, "completed", {"ok": True})
