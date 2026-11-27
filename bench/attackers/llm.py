"""Model client for the adaptive attackers (D13): any OpenAI-compatible chat endpoint.

Settings come from the experiment config's ``attacker_model`` block or, for missing keys, from
environment variables. API keys are read from the environment variable *named* in
``api_key_env``; they are never stored in configs or logs. Default model: Qwen3-32B (vLLM on the
A100 or Tinker). ``complete(system, user)`` returns the reply text with any <think> block removed.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass


@dataclass
class ModelSettings:
    model: str = "Qwen/Qwen3-32B"
    base_url: str = "http://127.0.0.1:8000/v1"
    api_key_env: str = "ATTACKER_API_KEY"     # name of the env var holding the key (vLLM accepts any)
    temperature: float = 0.8                  # D11: proposals must vary
    max_tokens: int = 4096
    timeout: float = 300.0

    @classmethod
    def from_dict(cls, d: dict | None) -> "ModelSettings":
        d = dict(d or {})
        s = cls()
        s.base_url = os.environ.get("ATTACKER_BASE_URL", s.base_url)
        s.model = os.environ.get("ATTACKER_MODEL", s.model)
        unknown = set(d) - set(cls.__dataclass_fields__)
        if unknown:
            raise ValueError(f"unknown attacker_model keys {sorted(unknown)}")
        for k, v in d.items():
            setattr(s, k, v)
        return s


class NullModel:
    """Dry-run stand-in: always returns an empty reply, which the session counts as an invalid proposal."""

    name = "null"

    def complete(self, system: str, user: str) -> str:
        return ""


class ChatClient:
    name = "openai-compatible"

    def __init__(self, settings: ModelSettings):
        from openai import OpenAI
        self.settings = settings
        self._client = OpenAI(base_url=settings.base_url, api_key=os.environ.get(settings.api_key_env, "EMPTY"),
                              timeout=settings.timeout)

    def complete(self, system: str, user: str) -> str:
        r = self._client.chat.completions.create(
            model=self.settings.model, temperature=self.settings.temperature, max_tokens=self.settings.max_tokens,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
        return strip_think(r.choices[0].message.content or "")


def strip_think(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


def build_model(cfg: dict | None, dry_run: bool):
    return NullModel() if dry_run else ChatClient(ModelSettings.from_dict(cfg))
