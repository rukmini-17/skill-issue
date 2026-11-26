"""Tinker backend (Thinking Machines), through its OpenAI-compatible endpoint.

Tinker documents an OpenAI-compatible endpoint (beta) at
``https://tinker.thinkingmachines.dev/services/tinker-prod/oai/api/v1``. Auth is
the Tinker API key (``api_key_env: TINKER_API_KEY``). ``model`` is either a
base-model ID (``Qwen/Qwen3-8B``, sampled directly; docs "Compatible APIs") or a
``tinker://...`` path for a trained checkpoint. ``tool_mode`` defaults to ``native``: the
smoke test (``scripts/tinker_smoke.py``, Qwen/Qwen3-8B, 2026-11-26) got the request with
``tools`` accepted, ``finish_reason: tool_calls`` and structured ``tool_calls`` back.

Prices: ``price`` in models.yaml (USD per million tokens: ``prefill``, ``cached_prefill``,
``sample``); Tinker bills prompt tokens as prefill too, not only sampled tokens.
``cost_usd`` and ``Budget`` in ``base`` use them. ``ready()`` does not call the API, so
health checks spend nothing.
"""

from __future__ import annotations

import re

from bench.backends.base import OpenAICompatModel

TINKER_BASE_URL = "https://tinker.thinkingmachines.dev/services/tinker-prod/oai/api/v1"
BASE_MODEL_ID = re.compile(r"^[A-Za-z0-9][\w.-]*/[A-Za-z0-9][\w.-]*$")   # e.g. Qwen/Qwen3-8B


class TinkerModel(OpenAICompatModel):
    backend = "tinker"
    default_tool_mode = "native"

    def __init__(self, name: str, base_url: str = TINKER_BASE_URL, **kw):
        super().__init__(name=name, base_url=base_url, **kw)
        m = str(self.model)
        if not (m.startswith("tinker://") or BASE_MODEL_ID.match(m)):
            raise ValueError(f"{name}: Tinker model must be a base-model ID like 'Qwen/Qwen3-8B' "
                             f"or a tinker:// checkpoint path, got {self.model!r}")

    def ready(self) -> bool:
        return bool(self._api_key and self._api_key != "none")

    def _fetch_server_info(self) -> dict:
        return {}                                   # no free metadata call
