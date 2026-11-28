"""The real harness (workstream B): ``Harness.run(spec) -> trace path``.

One call = one agent run (D9 step 5):

1. start the mock network (A's ``bench.mock`` when it exists, else the
   provisional dev mock) and switch on ``spec.mock_override`` (late_binding);
2. build the sandbox (copy + setup.sh + skills, B1). Attack runs
   (``spec.scenario is not None``) require ``netns``/``docker`` isolation
   (team decision 1 after checkpoint 1);
3. run the agent with monitoring (B2/B3), writing ``trace.jsonl``;
4. evaluate the task's ``success_check`` on the final workspace, inside the
   sandbox, and write ``success.json`` (also copied into ``meta.json["success"]``);
5. write ``meta.json`` and ``messages.json`` (full conversation), stop the mock,
   remove the sandbox (unless ``keep_workspace``).

``Harness()`` takes no required arguments, so the runner can load it by dotted
path. Models are looked up by name (``spec.model``) through
``bench.backends.make_model`` (``$CDB_MODELS``, else ``bench/configs/models.yaml``).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
import traceback
from pathlib import Path
from typing import Any, Callable

import yaml

from bench.harness import agent as agent_mod
from bench.harness.monitor import CommandMonitor, diff_snapshots, snapshot
from bench.harness.sandbox import SandboxError, make_sandbox, new_stage
from bench.harness.trace import MockLogTailer, TraceWriter
from bench.harness.tools import ToolExecutor
from bench.interfaces import RunSpec, StubMockNetwork, Task

REPO_ROOT = Path(__file__).resolve().parents[2]
REPOS = REPO_ROOT / "repos"


# --------------------------------------------------------------------------
# models
# --------------------------------------------------------------------------

def default_model_factory(name: str, seed: int):
    """Model ``name`` from the models file; the run's repeat seed unless the entry fixes one."""
    from bench.backends import make_model, model_config
    return make_model(name) if model_config(name).get("seed") is not None else make_model(name, seed=seed)


# --------------------------------------------------------------------------
# mock network
# --------------------------------------------------------------------------

def make_mock(kind: str):
    """``auto`` / ``a``: A's ``bench.mock.MockServer`` (A5, on main since data-v1).
    ``devmock``: B's provisional dev mock (kept for comparison tests). ``stub``: no network."""
    if kind == "stub":
        return StubMockNetwork(), "stub"
    if kind in ("auto", "a"):
        try:
            from bench.mock import MockServer
            return MockServer(), "bench.mock"
        except ImportError:
            if kind == "a":
                raise
    from bench.harness._devmock import DevMockNetwork
    return DevMockNetwork(), "harness-devmock"


DELTA_FILE_CAP = 5 * 1024 * 1024        # bytes per file in final_delta.tar.gz
DELTA_TOTAL_CAP = 25 * 1024 * 1024      # bytes per run


def save_delta(workspace: Path, before: dict, out: Path) -> dict:
    """Save the files the run created or modified (and list the deleted ones), so a run can be
    re-scored later with a changed success check: rebuild the task's workspace, apply the
    delta, run the check (``bench.harness.rescore``). Files over the caps are listed, not saved.
    Canary values may be in these files; they stay on disk like the trace (rule 12)."""
    import tarfile
    after = snapshot(workspace)
    changes = diff_snapshots(before, after)
    created = [e["path"] for e in changes if e["change"] == "created"]
    modified = [e["path"] for e in changes if e["change"] == "modified"]
    deleted = [e["path"] for e in changes if e["change"] == "deleted"]
    saved, skipped, total = [], [], 0
    with tarfile.open(out / "final_delta.tar.gz", "w:gz") as tar:
        for rel in sorted(created + modified):
            p = workspace / rel
            size = p.lstat().st_size if p.is_symlink() else p.stat().st_size
            if size > DELTA_FILE_CAP or total + size > DELTA_TOTAL_CAP:
                skipped.append({"path": rel, "size": size})
                continue
            tar.add(str(p), arcname=rel, recursive=False)
            saved.append(rel)
            total += size
    info = {"created": created, "modified": modified, "deleted": deleted,
            "saved": len(saved), "bytes": total, "skipped": skipped}
    (out / "final_delta.json").write_text(json.dumps(info, indent=1))
    return {k: (len(v) if isinstance(v, list) else v) for k, v in info.items()}


def host_info() -> dict:
    """Where the run happened, so a slow or hung node can be traced (pilot jobs 3-7 of the
    natural 8B array). Slurm variables are None outside a job."""
    env = os.environ
    return {"hostname": os.uname().nodename, "slurm_job_id": env.get("SLURM_JOB_ID"),
            "slurm_array_job_id": env.get("SLURM_ARRAY_JOB_ID"),
            "slurm_array_task_id": env.get("SLURM_ARRAY_TASK_ID"),
            "cuda_visible_devices": env.get("CUDA_VISIBLE_DEVICES")}


# --------------------------------------------------------------------------
# success checks
# --------------------------------------------------------------------------

_NUM = re.compile(r"(?<![\w.])[-+]?\d{1,3}(?:[,\u00a0\u202f]\d{3})+(?:\.\d+)?(?![\w])"
                  r"|(?<![\w.])[-+]?\d+(?:\.\d+)?(?![\w])")


def _numbers(text: str) -> set[float]:
    out = set()
    for m in _NUM.finditer(text):
        try:
            out.add(round(float(re.sub(r"[,\u00a0\u202f]", "", m.group())), 9))
        except ValueError:
            pass
    return out


def text_matches(text: str, sc: dict) -> bool:
    """Does ``text`` contain the check's needle? ``text`` / ``contains`` (both spellings occur in
    the data), or ``any_of`` (a list: any one is enough). Optional ``normalize`` (proposed for A,
    see NOTES.md "Success-check proposals"):

    * ``case``: compare case-insensitively;
    * ``whitespace``: runs of whitespace count as one space;
    * ``numbers``: a purely numeric needle matches a number in the text with the same value, so
      ``1121.75`` matches ``1,121.75`` and ``96.00`` matches ``96.0`` (whole numbers only, so
      ``96`` does not match ``196``).
    """
    needles = list(sc["any_of"]) if "any_of" in sc else [sc["text"] if "text" in sc else sc["contains"]]
    norm = set(sc.get("normalize") or [])
    unknown = norm - {"case", "whitespace", "numbers"}
    if unknown:
        raise ValueError(f"unknown normalize option(s) {sorted(unknown)}")
    nums = _numbers(text) if "numbers" in norm else set()
    hay = text
    if "whitespace" in norm:
        hay = " ".join(hay.split())
    if "case" in norm:
        hay = hay.casefold()
    for needle in needles:
        needle = str(needle)
        if "numbers" in norm and re.fullmatch(r"[-+]?[\d,]+(?:\.\d+)?", needle.strip()):
            if round(float(needle.replace(",", "")), 9) in nums:
                return True
            continue
        n = " ".join(needle.split()) if "whitespace" in norm else needle
        if (n.casefold() if "case" in norm else n) in hay:
            return True
    return False


def check_success(task: Task, sandbox) -> dict:
    sc = dict(task.success_check or {})
    kind = sc.get("type")
    out: dict[str, Any] = {"success": None, "checked": True, "type": kind}
    try:
        if kind in ("file_contains", "file_not_contains"):
            p = sandbox.workspace / sc["path"]
            real = Path(os.path.realpath(p))
            if not real.is_relative_to(sandbox.workspace) or not real.is_file():
                out.update(success=False if kind == "file_contains" else True,
                           reason=f"{sc['path']} does not exist")
                return out
            has = text_matches(real.read_text(encoding="utf-8", errors="replace"), sc)
            out.update(success=has if kind == "file_contains" else not has)
        elif kind == "command_exit":
            r = sandbox.run(sc["cmd"])
            want = int(sc.get("expect_exit", 0))
            out.update(success=r.exit == want, exit=r.exit, expect_exit=want,
                       output_tail=(r.stdout + r.stderr)[-2000:])
        else:
            out.update(checked=False, reason=f"unknown success_check type {kind!r}")
    except Exception as e:
        out.update(success=None, checked=False, reason=f"{type(e).__name__}: {e}")
    return out


# --------------------------------------------------------------------------
# harness
# --------------------------------------------------------------------------

class Harness:
    def __init__(self, model_factory: Callable[[str, int], Any] | None = None, mock: str = "auto",
                 isolation: str = "auto", observer: str = "auto", work_root: Path | None = None,
                 keep_workspace: bool = False, max_steps: int = agent_mod.MAX_STEPS,
                 run_timeout: float = agent_mod.RUN_TIMEOUT, ic2: bool = False,
                 prompt_path: Path | None = None, repos_dir: Path = REPOS,
                 one_call_per_turn: bool = True, setup: str = agent_mod.DEFAULT_SETUP,
                 save_delta: bool = True):
        self.model_factory = model_factory or default_model_factory
        self.mock_kind = mock
        self.isolation = os.environ.get("CDB_ISOLATION", isolation)
        self.observer = observer
        self.work_root = work_root
        self.keep_workspace = keep_workspace
        self.max_steps = max_steps
        self.run_timeout = run_timeout
        self.ic2 = ic2                       # pending IC-2; keep False until approved
        self.prompt_path = prompt_path or agent_mod.PROMPT_PATH
        self.repos_dir = Path(repos_dir)
        if setup not in agent_mod.SETUPS:
            raise ValueError(f"unknown setup {setup!r}; known: {sorted(agent_mod.SETUPS)}")
        self.setup = setup                   # agent_mod.SETUPS: max_tokens + truncation nudge
        self.save_delta = save_delta         # final_delta.tar.gz: files the run changed (re-scoring)
        # Team decision 6 (2026-11-26): one tool call per turn is the default for the pilot and
        # all later runs; False only for debugging. Recorded in meta.json.
        self.one_call_per_turn = one_call_per_turn

    def run(self, spec: RunSpec) -> Path:
        out = Path(spec.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        trace_path = out / "trace.jsonl"
        t_start = time.monotonic()
        meta: dict[str, Any] = {
            "run_id": spec.run_id, "harness": "bench.harness.run", "task_id": spec.task.task_id,
            "skill_id": spec.task.skill_id,
            "repo_id": spec.task.repo_id, "model": spec.model, "invocation": spec.invocation,
            "explicit_form": agent_mod.EXPLICIT_FORM if spec.invocation == "explicit" else None,
            "seed": spec.seed, "policy_runtime": getattr(spec.policy, "name", None),
            "attack_run": spec.scenario is not None, "ic2": self.ic2,
            "installed": {sid: v.version for sid, v in spec.installed.items()},
            "mock_override": str(spec.mock_override) if spec.mock_override else None,
            "observer": "none", "timings": {}, "host": host_info(),
        }
        mock, meta["mock"] = make_mock(self.mock_kind)
        sb = None
        stage = None
        tw = TraceWriter(trace_path, t0=t_start, ic2=self.ic2)
        try:
            # IC-1: the stage is made first so the mock serves what setup.sh builds there.
            stage = new_stage(self.work_root)
            meta["mock_root"] = str(stage)
            proxy = mock.start(spec.task.repo_id, out / "mock.jsonl", mock_root=stage)
            if spec.mock_override:
                mock.set_overrides(Path(spec.mock_override))
            tail = MockLogTailer(out / "mock.jsonl")

            t = time.monotonic()
            sb = make_sandbox(self.repos_dir / spec.task.repo_id, proxy, isolation=self.isolation,
                              require_network_isolation=spec.scenario is not None,
                              work_root=self.work_root, keep=self.keep_workspace, stage=stage)
            built = sb.build(spec.installed)
            meta["sandbox"] = built.to_json()
            meta["isolation"] = built.isolation
            meta["timings"]["build_s"] = round(time.monotonic() - t, 3)
            ws_before = snapshot(sb.workspace) if self.save_delta else None

            mon = CommandMonitor(sb, observer=self.observer, ic2=self.ic2)
            meta["observer"] = mon.observer
            if mon.probe_error:
                meta["observer_probe_error"] = mon.probe_error

            model = self.model_factory(spec.model, spec.seed)
            setup = agent_mod.SETUPS[self.setup]
            if setup["max_tokens"] and hasattr(model, "max_tokens"):
                model.max_tokens = setup["max_tokens"]
            meta["model_config"] = model.describe()
            meta["setup"] = self.setup
            meta["truncation_nudge"] = setup["truncation_nudge"]
            template = agent_mod.load_template(self.prompt_path)
            system = agent_mod.system_prompt(sb.workspace, spec.installed, template)
            user = agent_mod.user_prompt(spec.task.prompt, spec.task.skill_id, spec.invocation)
            meta["system_prompt_sha256"] = hashlib.sha256(system.encode()).hexdigest()

            ex = ToolExecutor(sb, mon, tw, spec.policy, spec.task, spec.installed, proxy, tail)
            t = time.monotonic()
            res = agent_mod.run_agent(model, ex, system, user, self.max_steps, self.run_timeout,
                                      one_call_per_turn=self.one_call_per_turn,
                                      truncation_nudge=setup["truncation_nudge"])
            meta["timings"]["agent_s"] = round(time.monotonic() - t, 3)
            meta["timings"]["model_s"] = round(res.model_seconds, 3)
            meta.update(run_end=res.reason, steps=res.steps, tool_calls=res.tool_calls,
                        malformed_calls=res.malformed, agent_error=res.error, agent_error_body=res.error_body,
                        agent_error_kind=res.error_kind, truncated_turns=res.truncated_turns,
                        usage=res.usage,
                        skill_loads=sorted(set(ex.skill_loads)), skill_uses=sorted(set(ex.skill_uses)),
                        final_text=res.final_text[:4000],
                        problems=ex.problems, one_call_per_turn=self.one_call_per_turn,
                        turns=res.turns, behaviour=res.behaviour(), nudges=res.nudges)
            from bench.backends.base import cost_usd
            cost = cost_usd(res.usage, (meta.get("model_config") or {}).get("price"))
            meta["cost_usd"] = round(cost, 6) if cost is not None else None
            if tail.bad:
                meta["mock_bad_lines"] = tail.bad
            out.mkdir(parents=True, exist_ok=True)     # never lose the run if its folder vanished mid-run
            agent_mod.dump_messages(res.messages, out / "messages.json")
            # Thinking text (server reasoning_content or stripped <think> blocks); on disk only.
            agent_mod.dump_messages(res.reasoning, out / "reasoning.json")

            if ws_before is not None:       # before the check, which may write (.coverage)
                try:
                    meta["final_delta"] = save_delta(sb.workspace, ws_before, out)
                except Exception as e:      # never lose a run over its delta
                    meta["final_delta"] = {"error": f"{type(e).__name__}: {e}"}
            t = time.monotonic()
            success = check_success(spec.task, sb)
            meta["timings"]["success_s"] = round(time.monotonic() - t, 3)
            meta["success"] = success
            (out / "success.json").write_text(json.dumps(success, indent=1))
        except Exception as e:
            meta["harness_error"] = f"{type(e).__name__}: {e}"
            meta["harness_traceback"] = traceback.format_exc()[-4000:]
            if tw.seq == 0 or not _has_run_end(trace_path):
                try:
                    tw.event("run_end", reason="error", steps=meta.get("steps", 0))
                except Exception:
                    pass
            if isinstance(e, SandboxError) and spec.scenario is not None:
                meta["refused"] = "attack run needs netns/docker isolation"
        finally:
            tw.close()
            if sb is not None:
                if self.keep_workspace:
                    meta["workspace"] = str(sb.workspace)
                sb.close()
            elif stage is not None:
                shutil.rmtree(stage, ignore_errors=True)   # sandbox was never created
            try:
                mock.stop()
            except Exception:
                pass
            meta["timings"]["total_s"] = round(time.monotonic() - t_start, 3)
            out.mkdir(parents=True, exist_ok=True)
            (out / "meta.json").write_text(json.dumps(meta, indent=1, default=str))
        return trace_path


def _has_run_end(trace_path: Path) -> bool:
    try:
        lines = trace_path.read_text().splitlines()
    except OSError:
        return False
    return bool(lines) and '"run_end"' in lines[-1]
