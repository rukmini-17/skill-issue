"""The `llm_reviewer` policy: an LLM reads the diff and both manifests and returns
allow / ask / deny.

For each update it builds a prompt (prompts/llm_reviewer.md) from the file diff and
the two manifests and asks a model, at temperature 0, whether the update lets the
skill do more than the user approved. The reply is parsed into a decision and a
one-line reason. Results are cached by a hash of both versions and the prompt, so
reviewing the same pair again is free and deterministic. No runtime checks.

It stands in for a human review that reads intent, not just declared permissions.
What it decides depends on the model and the prompt, both configurable.
"""

from __future__ import annotations

import difflib
import hashlib
import json
from pathlib import Path
from typing import Callable, Literal

from bench.interfaces import Decision, SkillVersion, Task, ToolCall
from bench.policies._capabilities import file_hashes

_PROMPT_PATH = Path(__file__).parent / "prompts" / "llm_reviewer.md"
_VALID: tuple[Decision, ...] = ("allow", "ask", "deny")

# A completion function: prompt -> raw model text. Injected for tests; the default
# builds an OpenAI-compatible client from models.yaml (workstream B's backends).
Completion = Callable[[str], str]


def _read_files(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for f in sorted(root.rglob("*")):
        if f.is_file():
            out[f.relative_to(root).as_posix()] = f.read_text(encoding="utf-8", errors="replace")
    return out


def _unified_diff(approved: Path, new: Path) -> str:
    old_files, new_files = _read_files(approved), _read_files(new)
    chunks: list[str] = []
    for rel in sorted(set(old_files) | set(new_files)):
        a = old_files.get(rel, "").splitlines(keepends=True)
        b = new_files.get(rel, "").splitlines(keepends=True)
        if a != b:
            chunks.extend(difflib.unified_diff(a, b, fromfile=f"a/{rel}", tofile=f"b/{rel}"))
    return "".join(chunks)


def parse_decision(text: str) -> tuple[Decision, str]:
    """Parse the model's two-line reply into (decision, reason). Lenient."""
    decision: Decision | None = None
    reason = ""
    for line in text.splitlines():
        low = line.strip().lower()
        if low.startswith("decision:"):
            token = low.split(":", 1)[1].strip()
            for d in _VALID:
                if token.startswith(d):
                    decision = d
                    break
        elif low.startswith("reason:"):
            reason = line.split(":", 1)[1].strip()
    if decision is None:
        # Could not parse a decision: fail safe to ask.
        return ("ask", f"unparseable reviewer response: {text[:200]!r}")
    return (decision, reason or "(no reason given)")


class LLMReviewerPolicy:
    name = "llm_reviewer"

    def __init__(
        self,
        complete: Completion | None = None,
        model: str = "qwen3-largest",
        cache_dir: Path | None = None,
        prompt_path: Path = _PROMPT_PATH,
    ):
        self._complete = complete
        self.model = model
        self._prompt_template = prompt_path.read_text(encoding="utf-8")
        self._cache_dir = cache_dir or (Path(__file__).parent / ".llm_reviewer_cache")

    # -- model client ------------------------------------------------------
    def _run_model(self, prompt: str) -> str:
        if self._complete is not None:
            return self._complete(prompt)
        raise RuntimeError(
            "llm_reviewer has no completion function configured. Inject `complete=` "
            "or wire B's OpenAI-compatible backend (bench/backends) for model "
            f"{self.model!r}."
        )

    # -- cache -------------------------------------------------------------
    def _cache_key(self, approved: SkillVersion, new: SkillVersion, prompt: str) -> str:
        h = hashlib.sha256()
        h.update(json.dumps(file_hashes(approved.root), sort_keys=True).encode())
        h.update(json.dumps(file_hashes(new.root), sort_keys=True).encode())
        h.update(self.model.encode())
        h.update(hashlib.sha256(prompt.encode()).digest())
        return h.hexdigest()

    def _cache_get(self, key: str) -> tuple[Decision, str] | None:
        f = self._cache_dir / f"{key}.json"
        if f.exists():
            obj = json.loads(f.read_text())
            return (obj["decision"], obj["reason"])
        return None

    def _cache_put(self, key: str, decision: Decision, reason: str) -> None:
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        (self._cache_dir / f"{key}.json").write_text(
            json.dumps({"decision": decision, "reason": reason})
        )

    # -- policy interface --------------------------------------------------
    def on_update(self, approved: SkillVersion, new: SkillVersion, task: Task) -> tuple[Decision, str]:
        prompt = self._prompt_template.format(
            approved_manifest=(approved.root / "manifest.json").read_text(encoding="utf-8"),
            new_manifest=(new.root / "manifest.json").read_text(encoding="utf-8"),
            diff=_unified_diff(approved.root, new.root),
        )
        key = self._cache_key(approved, new, prompt)
        cached = self._cache_get(key)
        if cached is not None:
            return cached
        decision, reason = parse_decision(self._run_model(prompt))
        self._cache_put(key, decision, reason)
        return (decision, reason)

    def on_tool_call(self, call: ToolCall, installed: SkillVersion, task: Task) -> Literal["allow", "block"]:
        return "allow"
