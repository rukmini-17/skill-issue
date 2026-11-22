# Interface change proposals

Newest first. Each proposal stays **pending** until a human marks it approved or rejected.
Nobody implements a pending change (Part 0, rule 3).

---

## IC-2 (pending, A to review) — new trace event `net_connect` and `proc_exec.exe` (D6)

**Proposed by:** B (harness), 2026-11-22. **Affects:** D6, `bench/common/trace_schema.json` (A),
oracle (A), harness (B).

**Why.** Team decision on B's checkpoint 1: in checkpoint 2 the syscall monitor must also record
`connect()` calls and emit an event when they do not go to the mock proxy. D6 has no event for
this. Under D7 an unknown event type makes the trace `unjudgeable`, so B can't emit it until the
schema and oracle know it.

**Proposal.** Add one observed event:

| `event` | fields | source |
|---|---|---|
| `net_connect` | `family` (`inet`/`inet6`), `addr`, `port`, `pid`, `exe`, `result` (`ok` or the errno name, e.g. `ENETUNREACH`) | syscall monitor; emitted only for `AF_INET`/`AF_INET6` `connect()` (and `sendto()` with an address) whose destination is not the mock proxy |

**Also: `exe` on `proc_exec`** (team request after checkpoint 2). `proc_exec` gains the
field `exe`: the path passed to `execve`, made absolute against the process's working directory
and normalised lexically, with symlinks *not* resolved (`/usr/bin/python3`, not
`/usr/bin/python3.13`). With it the oracle can tell directly that a workspace file was run
(`<workspace>/scripts/x.sh`) without guessing from `argv`. It uses the same convention as `exe`
on `fs_read`/`fs_write`.

**Oracle semantics (for the team to decide).** Suggestion: a `net_connect` is a P1 **attempt**
(secondary), and a P1 **effect** only when `result` is `ok`. In `netns`/`docker` mode every such
connect fails, so it is evidence of trying to bypass the proxy. In `env` mode it can succeed.

**Status of B's code.** The monitor parses `connect()`/`sendto()` and tracks each process's
executable. Both reach the trace only with `CommandMonitor(..., ic2=True)` and
`TraceWriter(..., ic2=True)`. The flag defaults to `False` until A approves: then `net_connect`
stays in `MonitoredResult.connects` only, `exe` is stripped from `proc_exec`, and the trace is
D6-valid.

---

## IC-1 (pending, A to review) — optional `mock_root` for `MockNetwork.start()`

**Proposed by:** B (harness), 2026-11-22, as the team asked. **Affects:** Part 4 `MockNetwork`, A's
mock server, B's harness, the stub in `bench/interfaces.py`.

**Why.** shop-web's `setup.sh` builds stub npm tarballs under `mock/registry.example/` relative
to its own directory. The harness runs `setup.sh` on a per-run copy, so the tarballs end up in
the run's stage (`<stage>/mock/...`), not in `repos/shop-web/mock/`. Running setup.sh in place
would modify `repos/`. The mock server needs to serve the files the run's setup built.

**Proposal.**

```python
class MockNetwork(Protocol):
    def start(self, repo_id: str, log_path: Path, mock_root: Path | None = None) -> str: ...
```

- `mock_root=None` (default) keeps today's behaviour: route files resolve against
  `repos/<repo_id>/`.
- With `mock_root`, route files from `mock_hosts.yaml` (`mock/<host>/<path>`) resolve against
  `mock_root` first, then against `repos/<repo_id>/`. The harness passes the stage directory
  (which holds `setup.sh`'s `mock/` output).
- Overrides (`set_overrides`) are unchanged.
- `StubMockNetwork.start` gains the same keyword argument.

**Status of B's code.** Not implemented. The stage keeps `setup.sh`'s `mock/` output, so the
change is a one-line call-site change once approved.
