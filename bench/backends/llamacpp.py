"""llama.cpp backend (COOK). ``llama-server --jinja`` on a GGUF file.

``--jinja`` makes llama-server apply the model's own chat template and parse
tool calls; ``--reasoning-format deepseek`` moves ``<think>`` text into
``reasoning_content``. Without either, the Qwen3 fallbacks in ``normalise_turn``
still work. ``-np 1`` gives the single agent the whole context. On COOK the
flags follow CSCF's validated example jobs for llm-r580-llamacpp and
llm-r615-llamacpp (``-ngl 999 -sm none -fa off -fit off -b 128 -ub 128 -t
$SLURM_CPUS_PER_TASK``); models.yaml sets them per entry. The examples'
sampling flags are not used: decoding comes from the request (temperature 0.2).
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
        fa = s.get("flash_attn")
        if fa is not None:                    # recent builds: --flash-attn on|off|auto (default auto)
            cmd += ["--flash-attn", fa if isinstance(fa, str) else ("on" if fa else "off")]
        # CSCF's validated COOK flags (llm-r580/r615 llamacpp examples): -sm none -fit off
        # -b 128 -ub 128 -t $SLURM_CPUS_PER_TASK. Each is emitted only when configured.
        for key, flag in (("split_mode", "-sm"), ("fit", "-fit"), ("batch_size", "-b"),
                          ("ubatch_size", "-ub"), ("threads", "-t")):
            v = s.get(key)
            if v is not None:
                cmd += [flag, ("on" if v else "off") if isinstance(v, bool) else str(v)]
        return cmd + [str(x) for x in s.get("extra_args", [])]
