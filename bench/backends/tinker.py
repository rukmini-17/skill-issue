"""Tinker backend (Thinking Machines), through its OpenAI-compatible endpoint.

Tinker documents an OpenAI-compatible endpoint (beta) at
``https://tinker.thinkingmachines.dev/services/tinker-prod/oai/api/v1``. Auth is
the Tinker API key (``api_key_env: TINKER_API_KEY``), and ``model`` is a
``tinker://...`` sampler path, not a Hugging Face model name. The docs do not
say whether ``/chat/completions`` accepts ``tools``, so this backend defaults to
``tool_mode: prompt`` (tools written into the prompt in Qwen3's own format,
replies parsed from ``<tool_call>`` text). Switch to ``native`` once checked.

Not run yet (Part 0 rule 9: Tinker credit). ``ready()`` does not call the API,
so health checks spend nothing. Unverified points are listed in
bench/harness/NOTES.md (Open questions).
"""

from __future__ import annotations

from bench.backends.base import OpenAICompatModel

TINKER_BASE_URL = "https://tinker.thinkingmachines.dev/services/tinker-prod/oai/api/v1"


class TinkerModel(OpenAICompatModel):
    backend = "tinker"
    default_tool_mode = "prompt"

    def __init__(self, name: str, base_url: str = TINKER_BASE_URL, **kw):
        super().__init__(name=name, base_url=base_url, **kw)
        if not str(self.model).startswith("tinker://"):
            raise ValueError(f"{name}: Tinker model must be a tinker:// sampler path, got {self.model!r}")

    def ready(self) -> bool:
        return bool(self._api_key and self._api_key != "none")

    def _fetch_server_info(self) -> dict:
        return {}                                   # no free metadata call
