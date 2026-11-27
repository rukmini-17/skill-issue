"""Model backends (workstream B, B5): one OpenAI-compatible client per serving stack.

    from bench.backends import make_model
    m = make_model("qwen3-8b-llamacpp")                 # from bench/configs/models.yaml
    m = make_model("qwen3-32b-vllm", temperature=0.0)   # overrides (LLM reviewer: temperature 0)
    turn = m.chat(messages, tools)                      # agent loop
    text = m.complete(messages)                         # no tools (reviewer, attacker)

The models file is ``$CDB_MODELS`` if set, else ``bench/configs/models.yaml``.
String values may use ``${VAR}`` or ``${VAR:-default}``; they are expanded when
the model is made, so an unset variable only matters for the model that uses it.
``api_key_env`` names the environment variable holding the key; keys are never
stored in the file.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

from bench.backends.base import BackendError, OpenAICompatModel
from bench.backends.llamacpp import LlamaCppModel
from bench.backends.tinker import TinkerModel
from bench.backends.vllm import VLLMModel

REPO_ROOT = Path(__file__).resolve().parents[2]
MODELS_FILE = REPO_ROOT / "bench" / "configs" / "models.yaml"

BACKENDS: dict[str, type[OpenAICompatModel]] = {
    "vllm": VLLMModel,
    "llamacpp": LlamaCppModel,
    "tinker": TinkerModel,
    "ollama": OpenAICompatModel,          # Mac development only
    "openai-compatible": OpenAICompatModel,
}

# keys a model entry may have besides the client's constructor arguments
# gpus / mem: what cook_submit.sh asks Slurm for (default 1 GPU; memory by partition).
META_KEYS = {"backend", "api_key_env", "notes", "partition", "candidate", "gpus", "mem"}
CLIENT_KEYS = {"base_url", "model", "family", "temperature", "max_tokens", "seed", "timeout", "retries",
               "retry_backoff", "tool_mode", "thinking", "top_p", "extra_body", "model_file",
               "quantization", "server", "hardware", "parallel_tool_calls", "send_parallel_tool_calls", "price"}


class ConfigError(ValueError):
    pass


def models_path(path: Path | str | None = None) -> Path:
    return Path(path or os.environ.get("CDB_MODELS") or MODELS_FILE)


def load_models(path: Path | str | None = None) -> dict[str, dict]:
    p = models_path(path)
    if not p.is_file():
        raise ConfigError(f"no model config: {p} does not exist (set $CDB_MODELS or create {MODELS_FILE})")
    cfg = (yaml.safe_load(p.read_text()) or {}).get("models") or {}
    if not isinstance(cfg, dict):
        raise ConfigError(f"{p}: 'models' must be a mapping")
    return cfg


_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def expand(value: Any, env: dict | None = None, where: str = "") -> Any:
    env = os.environ if env is None else env
    if isinstance(value, str):
        def sub(m):
            if m.group(1) in env and env[m.group(1)] != "":
                return env[m.group(1)]
            if m.group(2) is not None:
                return m.group(2)
            raise ConfigError(f"{where}: environment variable {m.group(1)} is not set")
        return _VAR.sub(sub, value)
    if isinstance(value, dict):
        return {k: expand(v, env, where) for k, v in value.items()}
    if isinstance(value, list):
        return [expand(v, env, where) for v in value]
    return value


def model_config(name: str, path: Path | str | None = None, env: dict | None = None) -> dict:
    cfg = load_models(path)
    if name not in cfg:
        raise ConfigError(f"model {name!r} not in {models_path(path)}; known: {sorted(cfg)}")
    entry = dict(cfg[name] or {})
    unknown = set(entry) - META_KEYS - CLIENT_KEYS
    if unknown:
        raise ConfigError(f"model {name!r}: unknown keys {sorted(unknown)}")
    if entry.get("backend") not in BACKENDS:
        raise ConfigError(f"model {name!r}: backend must be one of {sorted(BACKENDS)}, not {entry.get('backend')!r}")
    return expand(entry, env, where=f"model {name!r}")


def make_model(name: str, path: Path | str | None = None, env: dict | None = None, **overrides) -> OpenAICompatModel:
    c = model_config(name, path, env)
    env = os.environ if env is None else env
    cls = BACKENDS[c["backend"]]
    key_env = c.get("api_key_env")
    api_key = env.get(key_env, "") if key_env else "none"
    if key_env and not api_key and c["backend"] == "tinker":
        raise ConfigError(f"model {name!r}: ${key_env} is not set")
    kw = {k: v for k, v in c.items() if k in CLIENT_KEYS}
    kw.update(overrides)
    if c["backend"] in ("ollama", "openai-compatible"):
        kw["backend"] = c["backend"]
    return cls(name=name, api_key=api_key or "none", **kw)


__all__ = ["BACKENDS", "BackendError", "ConfigError", "OpenAICompatModel", "VLLMModel", "LlamaCppModel",
           "TinkerModel", "load_models", "model_config", "make_model", "expand"]
