# Workstream C — Policies — NOTES

## What's built

- `bench/interfaces.py` (M0): Part 4 contract, copied exactly, plus a stub for every interface so the pipeline imports and runs end to end.
- `bench/policies/` — the seven policies of D12, one module each, behind the `Policy` interface:
  - `none`, `pin_reapprove`, `new_permissions_only`, `capability_diff`,
    `deny_by_default_manifest`, `delegation_envelope`, `llm_reviewer`.
  - Each module docstring is a plain-language description of its rule (read by D's policy-aware attacker).
  - `_capabilities.py` — manifest loading, file hashing, glob subsumption, and the capability extractor (ported from `check_repo.py`).
  - `_runtime.py` — D2–D4 matching applied to a `ToolCall` (used by the two runtime policies).
  - `__init__.py` — `get_policy(name, **kwargs)` registry.
  - `prompts/llm_reviewer.md` — DRAFT reviewer prompt, needs team review.

Smoke-tested against `orders-api/data-quality-frameworks` v1 → benign_v2: pin_reapprove asks (reword), the four capability/manifest policies allow (matches `expected_capability_change: none`), runtime checks block out-of-scope read / disallowed host / `..` traversal.

## Deviations from the prompt (need noting / later reconciliation)

1. **Matching lives in `bench/policies/_capabilities.py` + `_runtime.py`, not `bench/common/match.py`.**
   C1 says to reuse `common/match.py` (workstream A). That module does not exist yet and is A's lane. To avoid blocking C, the glob/command/network matching is provisional here. **Seam to swap when A ships:** `_capabilities.glob_within/capabilities/file_hashes` and `_runtime.tool_call_allowed`. The provisional path matcher does lexical `..`/`.` resolution only — no symlink/real-path resolution (D2), because `on_tool_call` does not have the live workspace root. A's matcher should replace this.

## Judgment calls (faithful to D12, but flagged)

- **"widens" / "exceeds":** a permission/capability list widens if, after glob
  subsumption, it allows a path/host/command not previously allowed. A benign
  reword that adds no new entry does not widen. Matches what `check_repo.py`
  asserts for benign versions.
- **`delegation_envelope` capability check:** hosts compared by membership against
  `delegation.network`; paths against `delegation.read + delegation.write`;
  commands via D3 argv-prefix against `delegation.exec`; extracted `deps` are not
  checked (delegation has no dependency field).

## Open questions

- `llm_reviewer` needs B's OpenAI-compatible backend (or an injected `complete=`)
  to actually run; parsing + caching are done and unit-testable with a fake model.
- Confirm with team: should `delegation_envelope` treat extracted `deps` as always
  in-envelope (current) or add a dependency dimension to the delegation?
