"""llama.cpp backend (COOK). ``llama-server --jinja`` on a GGUF file.

``--jinja`` makes llama-server apply the model's own chat template and parse
tool calls; ``--reasoning-format deepseek`` moves ``<think>`` text into
``reasoning_content``. Without either, the Qwen3 fallbacks in ``normalise_turn``
still work. ``-np 1`` gives the single agent the whole context.
"""

from __future__ import annotations

import os

from bench.backends.base import OpenAICompatModel


class LlamaCppModel(OpenAICompatModel):
    backend = "llamacpp"

    def backend_extra_body(self) -> dict:
        body: dict = {"cache_prompt": True}
        if self.thinking is not None:
            body["chat_template_kwargs"] = {"enable_thinking": self.thinking}
        return body

    def health_url(self) -> str:
        return self.server_root + "/health"          # 503 while the model loads

    def _fetch_server_info(self) -> dict:
        p = self._get(self.server_root + "/props").json()
        gen = p.get("default_generation_settings") or {}
        return {k: v for k, v in {"model_path": p.get("model_path"), "n_ctx": gen.get("n_ctx") or p.get("n_ctx"),
                                  "build_info": p.get("build_info")}.items() if v is not None}

    def server_command(self) -> list[str]:
        s = self.server
        if not self.model_file:
            raise ValueError(f"{self.name}: llamacpp needs model_file")
        cmd = [s.get("binary") or os.environ.get("LLAMA_SERVER", "llama-server"), "-m", self.model_file,
               "--jinja", "--host", "127.0.0.1", "--port", str(self.port or 8080), "--alias", self.model,
               "-c", str(s.get("ctx_size", 32768)), "-ngl", str(s.get("n_gpu_layers", 99)), "-np", "1",
               "--reasoning-format", s.get("reasoning_format", "deepseek"), "--seed", str(s.get("seed", 0))]
        if s.get("flash_attn"):
            cmd += ["-fa"]
        return cmd + [str(x) for x in s.get("extra_args", [])]
