"""Trace writing (workstream B, D6 trace schema v2).

``TraceWriter`` owns the single ``seq`` counter shared by agent tool lines and
observed events, and the ``t`` clock (seconds since the run started). Every
line is flushed as it is written, so a crashed run still leaves a readable
prefix.

``MockLogTailer`` reads the mock server's log incrementally and turns each
request into a D6 ``net_observed`` event, which the harness writes into the
trace after the tool call that caused it.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

TOOL_STATUSES = ("requested", "blocked", "completed", "failed")

# D6 field lists, used to keep emitted events to exactly the schema's fields.
EVENT_FIELDS: dict[str, tuple[str, ...]] = {
    "skill_load": ("skill_id", "version", "path"),
    "fs_read": ("path", "pid", "exe"),
    "fs_write": ("path", "op", "pid", "exe"),
    "proc_exec": ("argv", "pid", "ppid"),
    "net_observed": ("host", "method", "url", "headers", "body", "served"),
    "fs_diff": ("path", "change"),
    "policy_decision": ("phase", "policy", "decision", "from_version", "to_version", "reason"),
    "run_end": ("reason", "steps"),
    # pending IC-2; only written when the harness is told to (emit_net_connect)
    "net_connect": ("family", "addr", "port", "pid", "exe", "result"),
}


class TraceWriter:
    def __init__(self, path: Path, t0: float | None = None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("w", encoding="utf-8")
        self.t0 = time.monotonic() if t0 is None else t0
        self.seq = 0

    def _t(self) -> float:
        return round(time.monotonic() - self.t0, 3)

    def _write(self, obj: dict[str, Any]) -> dict[str, Any]:
        line = {"seq": self.seq, "t": self._t(), **obj}
        self.seq += 1
        self._fh.write(json.dumps(line, ensure_ascii=False) + "\n")
        self._fh.flush()
        return line

    def tool(self, tool: str, args: dict, status: str, **extra: Any) -> dict[str, Any]:
        """An agent tool line. ``extra``: ``exit``/``ok``, ``out_bytes``, ``blocked_by``, ``error``."""
        if status not in TOOL_STATUSES:
            raise ValueError(f"bad status {status!r}")
        return self._write({"tool": tool, "args": args, "status": status, **extra})

    def event(self, event: str, **fields: Any) -> dict[str, Any]:
        if event not in EVENT_FIELDS:
            raise ValueError(f"unknown event {event!r}")
        allowed = EVENT_FIELDS[event]
        extra = set(fields) - set(allowed)
        if extra:
            raise ValueError(f"{event}: fields {sorted(extra)} not in D6")
        return self._write({"event": event, **{k: fields[k] for k in allowed if k in fields}})

    def events(self, evs: list[dict[str, Any]]) -> None:
        for e in evs:
            e = dict(e)
            self.event(e.pop("event"), **e)

    def close(self) -> None:
        if not self._fh.closed:
            self._fh.close()

    def __enter__(self) -> "TraceWriter":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class MockLogTailer:
    """Reads complete JSON lines appended to the mock log since the last call.

    Accepts the mock's lines whether or not they already carry
    ``"event": "net_observed"``; ``seq``/``t`` from the mock are dropped (the
    trace assigns its own). Lines that are not JSON objects are returned in
    ``bad`` so the harness can record them in meta.json.
    """

    def __init__(self, log_path: Path):
        self.log_path = Path(log_path)
        self._pos = 0
        self._partial = b""
        self.bad: list[str] = []

    def drain(self) -> list[dict[str, Any]]:
        if not self.log_path.exists():
            return []
        with self.log_path.open("rb") as fh:
            fh.seek(self._pos)
            data = fh.read()
            self._pos = fh.tell()
        data = self._partial + data
        lines = data.split(b"\n")
        self._partial = lines.pop()          # incomplete last line (no newline yet)
        out: list[dict[str, Any]] = []
        for raw in lines:
            if not raw.strip():
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                self.bad.append(raw.decode("utf-8", "replace")[:500])
                continue
            if not isinstance(obj, dict) or obj.get("event", "net_observed") != "net_observed":
                self.bad.append(raw.decode("utf-8", "replace")[:500])
                continue
            ev = {"event": "net_observed"}
            for k in EVENT_FIELDS["net_observed"]:
                if k in obj:
                    ev[k] = obj[k]
            out.append(ev)
        return out
