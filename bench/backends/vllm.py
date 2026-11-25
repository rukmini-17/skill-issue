"""vLLM backend (A100). ``vllm serve`` with the hermes tool parser and the qwen3 reasoning parser."""

from __future__ import annotations

from bench.backends.base import OpenAICompatModel


class VLLMModel(OpenAICompatModel):
    backend = "vllm"

    def backend_extra_body(self) -> dict:
        return {"chat_template_kwargs": {"enable_thinking": self.thinking}} if self.thinking is not None else {}

    def health_url(self) -> str:
        return self.server_root + "/health"

    def server_command(self) -> list[str]:
        s = self.server
        cmd = [s.get("binary", "vllm"), "serve", s.get("weights", self.model),
               "--served-model-name", self.model, "--host", "127.0.0.1", "--port", str(self.port or 8000),
               "--enable-auto-tool-choice", "--tool-call-parser", s.get("tool_call_parser", "hermes"),
               "--max-model-len", str(s.get("ctx_size", 32768)),
               "--gpu-memory-utilization", str(s.get("gpu_memory_utilization", 0.9)),
               "--seed", str(s.get("seed", 0))]
        if s.get("reasoning_parser", "qwen3"):
            cmd += ["--reasoning-parser", s.get("reasoning_parser", "qwen3")]
        if s.get("quantization_flag"):              # vLLM reads AWQ/GPTQ from the checkpoint otherwise
            cmd += ["--quantization", s["quantization_flag"]]
        return cmd + [str(x) for x in s.get("extra_args", [])]
