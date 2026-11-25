"""Path helpers for the B tests (unique module name so it can't clash with other test folders)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REPOS = ROOT / "repos"


def url(srv) -> str:
    """Proxy URL of a test proxy server."""
    return f"http://127.0.0.1:{srv.server_address[1]}"


def load_task(repo_id: str, task_id: str):
    """Task from repos/<repo>/tasks/<id>.yaml (A's loader will replace this)."""
    import yaml

    from bench.interfaces import Delegation, Task
    p = REPOS / repo_id / "tasks" / f"{task_id}.yaml"
    d = yaml.safe_load(p.read_text())
    dl = d["delegation"]
    return Task(repo_id, d["task_id"], d["skill_id"], d["prompt"],
                Delegation(*(tuple(dl.get(k) or ()) for k in ("read", "write", "exec", "network",
                                                               "protected_data"))),
                d["success_check"], p.with_suffix(".reference"))


TOOL_STATUSES = {"requested", "blocked", "completed", "failed"}


def check_trace_v2(path):
    """Structural D6 check until A's trace_schema.json lands. Returns the parsed lines."""
    import json

    from bench.harness.trace import EVENT_FIELDS
    lines = [json.loads(l) for l in Path(path).read_text().splitlines()]
    assert lines, "empty trace"
    assert [l["seq"] for l in lines] == list(range(len(lines)))
    ts = [l["t"] for l in lines]
    assert ts == sorted(ts) and ts[0] >= 0
    for l in lines:
        if "tool" in l:
            assert "event" not in l
            assert l["tool"] in {"read_file", "write_file", "list_dir", "run_command", "http_request"}
            assert isinstance(l["args"], dict) and l["status"] in TOOL_STATUSES
            assert set(l) <= {"seq", "t", "tool", "args", "status", "exit", "ok", "out_bytes", "blocked_by"}
            if l["status"] == "blocked":
                assert l["blocked_by"]
            if l["status"] in ("completed", "failed"):
                assert ("exit" in l) if l["tool"] == "run_command" else ("ok" in l)
                assert isinstance(l["out_bytes"], int)
        else:
            assert l["event"] in EVENT_FIELDS, l
            assert set(l) == {"seq", "t", "event", *EVENT_FIELDS[l["event"]]}, l
    assert lines[-1].get("event") == "run_end"
    # every final tool line follows its requested line
    open_req = 0
    for l in lines:
        if "tool" in l:
            if l["status"] == "requested":
                assert open_req == 0
                open_req = 1
            else:
                assert open_req == 1
                open_req = 0
    assert open_req == 0
    return lines
