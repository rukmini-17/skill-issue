"""OpenAI-compatible chat client shared by all backends (workstream B, B5).

Every backend (``vllm``, ``llamacpp``, ``tinker``, plus ``ollama`` for Mac
development) is an OpenAI-compatible ``/v1/chat/completions`` endpoint. The
subclasses only change defaults, health checks, server metadata and the
command that starts the server. They all implement the interface the agent
loop expects (``bench.harness.model.ChatModel``):

    chat(messages, tools) -> AssistantTurn
    describe() -> dict          # backend, model file, quantization, decoding (meta.json)

C's ``llm_reviewer`` and D's attacker use the same clients without tools:
``chat(messages)`` or ``complete(messages) -> str``.

Tool modes:

* ``native``: tool schemas go in the request's ``tools`` field and the server
  parses tool calls (vLLM ``--tool-call-parser hermes``, llama.cpp ``--jinja``).
  If the server leaves ``<tool_call>`` text in the content, the Qwen3 fallback in
  ``normalise_turn`` still recovers it.
* ``prompt``: for servers whose tool support is unknown (Tinker). The client
  writes the tool schemas into the system message in Qwen3's own (hermes)
  format, turns earlier tool calls and results into text the way Qwen3's chat
  template does, sends no ``tools`` field, and parses ``<tool_call>`` blocks from
  the reply. See ``hermes.py``.

Errors: every failure is raised as ``BackendError`` with a ``kind``
(``connection``, ``timeout``, ``server``, ``rate_limit``, ``context_length``,
``bad_request``, ``auth``, ``not_found``, ``bad_response``). ``connection``,
``timeout``, ``server`` and ``rate_limit`` are retried ``retries`` times with
exponential backoff; the others fail at once. The agent loop records the error
and ends the run with ``reason: error`` (meta.json ``agent_error_kind``).
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from bench.harness.model import AssistantTurn, ToolCallRequest, normalise_turn
from bench.backends import hermes

RETRYABLE = frozenset({"connection", "timeout", "server", "rate_limit"})
TOOL_MODES = ("native", "prompt")


class BackendError(RuntimeError):
    """``body``: the server's response body for an HTTP error (4xx/5xx), as sent, up to 4000
    chars, plus a few response headers that identify the request. Recorded in meta.json
    (``agent_error_body``) because a 422's reason is usually only in the body."""

    def __init__(self, kind: str, message: str, status: int | None = None, body: str | None = None):
        super().__init__(f"[{kind}] {message}")
        self.kind = kind
        self.status = status
        self.body = body


_ID_HEADERS = ("content-type", "x-request-id", "request-id", "x-amzn-requestid", "cf-ray")


def _response_body(exc) -> str | None:
    """The HTTP response body of an ``openai.APIStatusError`` (text, else the parsed body)."""
    resp = getattr(exc, "response", None)
    text = None
    try:
        text = resp.text if resp is not None else None
    except Exception:                       # body already consumed / not readable
        text = None
    if not text and getattr(exc, "body", None) is not None:
        text = exc.body if isinstance(exc.body, str) else json.dumps(exc.body, default=str)
    hdrs = {}
    try:
        hdrs = {h: resp.headers[h] for h in _ID_HEADERS if resp is not None and h in resp.headers}
    except Exception:
        hdrs = {}
    if not text and not hdrs:
        return None
    out = (text or "(empty body)")[:4000]
    return out + (f"\n[headers] {json.dumps(hdrs)}" if hdrs else "")


def classify(exc: Exception) -> BackendError:
    """Map an ``openai`` / ``httpx`` exception to a ``BackendError``."""
    import openai
    if isinstance(exc, BackendError):
        return exc
    if isinstance(exc, openai.APITimeoutError):
        return BackendError("timeout", str(exc))
    if isinstance(exc, openai.APIConnectionError):
        return BackendError("connection", str(exc))
    if isinstance(exc, openai.APIStatusError):
        st = exc.status_code
        text = str(exc).lower()
        if st in (400, 413, 422) and ("context" in text or "too long" in text or "maximum" in text
                                      or "exceed" in text):
            kind = "context_length"
        elif st == 429:
            kind = "rate_limit"
        elif st >= 500:
            kind = "server"
        elif st in (401, 403):
            kind = "auth"
        elif st == 404:
            kind = "not_found"
        else:
            kind = "bad_request"
        body = _response_body(exc)
        short = f" | body: {body[:500]}" if body and body[:500] not in str(exc) else ""
        return BackendError(kind, f"HTTP {st}: {exc}{short}"[:2000], st, body)
    return BackendError("bad_response", f"{type(exc).__name__}: {exc}"[:2000])


def cost_usd(usage: dict | None, price: dict | None) -> float | None:
    """USD for ``usage`` at ``price`` (USD per million tokens: ``prefill``, ``cached_prefill``,
    ``sample``). Tinker bills prompt tokens as prefill and sampled tokens as sample; cached
    prefill is cheaper (80 % off). Prompt tokens the server did not report as cached are billed
    at the full prefill price, so the estimate errs high. None without a price."""
    if not price or usage is None:
        return None
    prompt = int(usage.get("prompt_tokens") or 0)
    cached = min(int(usage.get("cached_prompt_tokens") or 0), prompt)
    pre, cpre = float(price.get("prefill", 0)), float(price.get("cached_prefill", price.get("prefill", 0)))
    return ((prompt - cached) * pre + cached * cpre
            + int(usage.get("completion_tokens") or 0) * float(price.get("sample", 0))) / 1e6


class Budget:
    """A hard USD cap shared by every model call of one job (thread-safe). Before each request
    the model asks ``reserve`` for that request's worst case (estimated prompt at full prefill
    price + max_tokens at the sample price); if spent + worst case exceeds the cap, the request
    is not sent and ``BackendError("budget")`` ends the run. After the response, ``add`` books
    the real cost. So spending never passes the cap."""

    def __init__(self, cap_usd: float):
        import threading
        self.cap = float(cap_usd)
        self.spent = 0.0
        self.refused = 0
        self._lock = threading.Lock()

    def reserve(self, worst_usd: float) -> None:
        with self._lock:
            if self.spent + worst_usd > self.cap:
                self.refused += 1
                raise BackendError("budget", f"job budget ${self.cap:.2f} reached "
                                             f"(spent ${self.spent:.4f}, next call up to ${worst_usd:.4f})")

    def add(self, usd: float | None) -> None:
        if usd:
            with self._lock:
                self.spent += usd


class OpenAICompatModel:
    """Any OpenAI-compatible endpoint. Decoding defaults follow D11 (agent temperature 0.2)."""

    backend = "openai-compatible"
    default_tool_mode = "native"

    def __init__(self, name: str, base_url: str, model: str, api_key: str = "none",
                 family: str = "qwen3", temperature: float = 0.2, max_tokens: int = 4096,
                 seed: int | None = None, timeout: float = 600.0, retries: int = 3,
                 retry_backoff: float = 2.0, tool_mode: str | None = None,
                 thinking: bool | None = None, top_p: float | None = None,
                 parallel_tool_calls: bool | None = False, send_parallel_tool_calls: bool = True,
                 extra_body: dict | None = None, model_file: str | None = None,
                 quantization: str | None = None, server: dict | None = None,
                 hardware: str | None = None, backend: str | None = None,
                 price: dict | None = None):
        from openai import OpenAI          # lazy, so tests without a model don't need it
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.family = family
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.seed = seed
        self.timeout = timeout
        self.retries = int(retries)
        self.retry_backoff = float(retry_backoff)
        self.tool_mode = tool_mode or self.default_tool_mode
        if self.tool_mode not in TOOL_MODES:
            raise ValueError(f"tool_mode must be one of {TOOL_MODES}, not {self.tool_mode!r}")
        self.thinking = thinking
        # Team decision 6: ask the server for at most one tool call per turn (native tool mode
        # only; null in models.yaml omits it for a server that rejects the field). The harness
        # enforces one call per turn either way.
        self.parallel_tool_calls = parallel_tool_calls
        # Per model: False = never send the field (Tinker, job 3444: with
        # parallel_tool_calls=false it rejects a *response* that has several tool calls with
        # HTTP 422, so the field breaks runs instead of limiting calls). One call per turn is
        # still enforced by the harness (decision 6 (b)).
        self.send_parallel_tool_calls = bool(send_parallel_tool_calls)
        self.top_p = top_p
        self.extra_body = dict(extra_body or {})
        self.model_file = model_file
        self.quantization = quantization
        self.server = dict(server or {})
        self.hardware = hardware
        if backend:
            self.backend = backend
        self._api_key = api_key
        self.price = dict(price) if price else None    # USD per million tokens (cost_usd)
        self.budget: Budget | None = None              # set by the pilot (--max-cost-usd)
        self._server_info: dict | None = None
        # max_retries=0: retries are ours (classified, logged, backoff configurable)
        self._client = OpenAI(base_url=self.base_url, api_key=api_key or "none", timeout=timeout,
                              max_retries=0)
        self.retry_log: list[dict] = []

    # ---------------------------------------------------------------- meta

    def describe(self) -> dict:
        d = {"name": self.name, "backend": self.backend, "base_url": self.base_url, "model": self.model,
             "model_file": self.model_file, "quantization": self.quantization, "family": self.family,
             "hardware": self.hardware, "tool_mode": self.tool_mode, "price": self.price,
             "ctx_size": (self.server or {}).get("ctx_size"),
             "decoding": {"temperature": self.temperature, "max_tokens": self.max_tokens,
                          "seed": self.seed, "top_p": self.top_p, "thinking": self.thinking,
                          "parallel_tool_calls": self.parallel_tool_calls if self._sends_parallel() else None,
                          "send_parallel_tool_calls": self.send_parallel_tool_calls,
                          **({"extra_body": self.extra_body} if self.extra_body else {})}}
        info = self.server_info()
        if info:
            d["server_info"] = info
        return d

    def server_info(self) -> dict:
        """Best-effort facts from the running server (model path, context size). Cached; never raises."""
        if self._server_info is None:
            try:
                self._server_info = self._fetch_server_info() or {}
            except Exception as e:                       # metadata only; a run must not fail on it
                self._server_info = {"error": f"{type(e).__name__}: {e}"[:300]}
        return self._server_info

    def _fetch_server_info(self) -> dict:
        r = self._get(self.base_url + "/models")
        data = (r.json().get("data") or [{}])
        m = next((x for x in data if x.get("id") == self.model), data[0] if data else {})
        return {k: m[k] for k in ("id", "root", "max_model_len", "owned_by") if k in m}

    # ------------------------------------------------------------- health

    @property
    def server_root(self) -> str:
        """``http://host:port`` without the ``/v1`` suffix."""
        u = urlsplit(self.base_url)
        path = u.path[:-3] if u.path.endswith("/v1") else u.path
        return urlunsplit((u.scheme, u.netloc, path, "", "")).rstrip("/")

    @property
    def port(self) -> int | None:
        return urlsplit(self.base_url).port

    def health_url(self) -> str:
        return self.base_url + "/models"

    def ready(self) -> bool:
        try:
            return self._get(self.health_url(), timeout=5).status_code == 200
        except Exception:
            return False

    def wait_ready(self, timeout: float = 600.0, interval: float = 2.0) -> bool:
        end = time.monotonic() + timeout
        while True:
            if self.ready():
                return True
            if time.monotonic() >= end:
                return False
            time.sleep(interval)

    def server_command(self) -> list[str]:
        """Command line that starts this model's server (pilot scripts). Not every backend has one."""
        raise NotImplementedError(f"backend {self.backend!r} has no local server command")

    def _get(self, url: str, timeout: float = 10.0):
        import httpx
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key not in (None, "", "none") else {}
        return httpx.get(url, timeout=timeout, headers=headers)

    # --------------------------------------------------------------- chat

    def _sends_parallel(self) -> bool:
        """Is ``parallel_tool_calls`` in the request? Native tool mode only, not null, and the
        entry's ``send_parallel_tool_calls`` (default true)."""
        return (self.tool_mode == "native" and self.parallel_tool_calls is not None
                and self.send_parallel_tool_calls)

    def backend_extra_body(self) -> dict:
        """Backend-specific request fields (``chat_template_kwargs`` and the like)."""
        return {}

    def build_request(self, messages: list[dict], tools: list[dict] | None) -> dict[str, Any]:
        kw: dict[str, Any] = dict(model=self.model, temperature=self.temperature, max_tokens=self.max_tokens)
        if tools and self.tool_mode == "native":
            kw.update(messages=messages, tools=tools, tool_choice="auto")
            if self._sends_parallel():
                kw["parallel_tool_calls"] = self.parallel_tool_calls
        elif tools:
            kw["messages"] = hermes.to_prompt_messages(messages, tools)
        else:
            kw["messages"] = hermes.to_prompt_messages(messages, None) if self.tool_mode == "prompt" else messages
        if self.seed is not None:
            kw["seed"] = self.seed
        if self.top_p is not None:
            kw["top_p"] = self.top_p
        extra = {**self.backend_extra_body(), **self.extra_body}
        if extra:
            kw["extra_body"] = extra
        return kw

    def _create(self, kw: dict):
        attempt = 0
        while True:
            try:
                return self._client.chat.completions.create(**kw)
            except Exception as e:
                err = self._redact(classify(e))
                if err.kind not in RETRYABLE or attempt >= self.retries:
                    raise err from e
                wait = self.retry_backoff * (2 ** attempt)
                self.retry_log.append({"attempt": attempt + 1, "kind": err.kind, "wait_s": wait,
                                       "error": str(err)[:300]})
                attempt += 1
                time.sleep(wait)

    def _redact(self, err: BackendError) -> BackendError:
        """Never let the API key reach meta.json, messages or logs through an error text."""
        key = self._api_key
        if key and key != "none" and (key in str(err) or key in (err.body or "")):
            return BackendError(err.kind, str(err).replace(key, "<redacted>").split("] ", 1)[-1], err.status,
                                (err.body or "").replace(key, "<redacted>") or None)
        return err

    def worst_turn_cost(self, kw: dict) -> float:
        """Upper estimate of one request's cost: prompt (JSON chars / 3) at full prefill price
        plus max_tokens at the sample price."""
        if not self.price:
            return 0.0
        chars = len(json.dumps(kw.get("messages") or [])) + len(json.dumps(kw.get("tools") or []))
        return cost_usd({"prompt_tokens": chars // 3 + 1, "completion_tokens": kw.get("max_tokens") or 0},
                        self.price) or 0.0

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> AssistantTurn:
        t0 = time.monotonic()
        kw = self.build_request(messages, tools)
        if self.budget is not None:
            self.budget.reserve(self.worst_turn_cost(kw))
        resp = self._create(kw)
        try:
            choice = resp.choices[0]
            msg = choice.message
        except (AttributeError, IndexError, TypeError) as e:
            raise BackendError("bad_response", f"no choices in response: {str(resp)[:300]}") from e
        calls = [ToolCallRequest(tc.id or f"call_{uuid.uuid4().hex[:12]}", tc.function.name or "",
                                 tc.function.arguments or "")
                 for tc in (msg.tool_calls or []) if getattr(tc, "function", None)]
        reasoning = getattr(msg, "reasoning_content", None) or getattr(msg, "reasoning", None) or ""
        family = "qwen3" if (tools and self.tool_mode == "prompt") else self.family
        turn = normalise_turn(msg.content, calls, family if tools else "", reasoning)
        turn.finish_reason = choice.finish_reason
        if resp.usage:
            turn.usage = {"prompt_tokens": resp.usage.prompt_tokens or 0,
                          "completion_tokens": resp.usage.completion_tokens or 0}
            details = getattr(resp.usage, "prompt_tokens_details", None)
            cached = getattr(details, "cached_tokens", None) if details is not None else None
            if cached:
                turn.usage["cached_prompt_tokens"] = int(cached)
        if self.budget is not None:
            self.budget.add(cost_usd(turn.usage, self.price) if turn.usage else self.worst_turn_cost(kw))
        turn.seconds = time.monotonic() - t0
        return turn

    def complete(self, messages: list[dict]) -> str:
        """Plain text answer, no tools (LLM reviewer, attacker). Thinking is removed."""
        return self.chat(messages, None).content
