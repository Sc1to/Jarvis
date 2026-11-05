"""LLM client: the interface, the real OpenAI-compatible client, and a fake for tests.

All model calls in bookforge go through an object with the `LLMClient` interface.
The real client talks to the two colibri servers (config `models.writer` and
`models.critic`), retries transient failures, and logs every call to
books/<book>/logs/calls.jsonl.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Protocol, Sequence

import httpx

from .calllog import CallLog
from .config import Config, ModelEndpoint
from .errors import BookforgeError

log = logging.getLogger("platform_bookforge.llm")

Messages = Sequence[dict]

# Options a caller may pass through to the server, plus `draft` (picks the temperature).
ALLOWED_OPTIONS = {"temperature", "max_tokens", "top_p", "stop", "seed", "draft"}
RETRY_STATUS = {408, 429, 500, 502, 503, 504}


class LLMClient(Protocol):
    def complete(self, role: str, messages: Messages, **options) -> str:
        """Return the model's reply. `role` is 'writer' or 'critic'."""
        ...


class FakeLLMExhausted(AssertionError):
    """A test asked for more replies than it scripted."""


@dataclass
class FakeLLMClient:
    """Scripted replies, consumed in order per role. Records every call.

    `script` maps role -> list of replies; a reply may be a string or a function
    of the messages. A '*' key is the fallback for roles without their own list.
    """

    script: dict[str, list[str | Callable[[Messages], str]]] = field(default_factory=dict)
    calls: list[dict] = field(default_factory=list)

    def complete(self, role: str, messages: Messages, **options) -> str:
        self.calls.append({"role": role, "messages": [dict(m) for m in messages], "options": options})
        queue = self.script.get(role) or self.script.get("*")
        if not queue:
            raise FakeLLMExhausted(f"no scripted reply left for role '{role}'")
        reply = queue.pop(0)
        return reply(messages) if callable(reply) else reply


class LLMError(BookforgeError):
    """A model call failed for good (after retries, or not worth retrying)."""


class _Retryable(Exception):
    pass


class HttpLLMClient:
    """OpenAI-compatible chat completions against a colibri server.

    Retries connection errors, timeouts, 408/429 and 5xx with exponential backoff.
    Raises LLMError for anything else (unknown model, bad request, cut-off reply).
    """

    def __init__(
        self,
        config: Config,
        call_log: CallLog | None = None,
        attempts: int = 3,
        backoff_seconds: float = 2.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._models = {"writer": config.models.writer, "critic": config.models.critic}
        self._log = call_log or CallLog(None)
        self._attempts = max(1, attempts)
        self._backoff = backoff_seconds
        self._transport = transport
        self._sleep = sleep

    def complete(self, role: str, messages: Messages, **options) -> str:
        endpoint = self._models.get(role)
        if endpoint is None:
            raise LLMError(f"unknown model role '{role}' (expected 'writer' or 'critic')")
        if not endpoint.model:
            raise LLMError(f"models.{role}.model is not set in the config (see `c/coli status` for the id)")
        unknown = set(options) - ALLOWED_OPTIONS
        if unknown:
            raise LLMError(f"unsupported option(s): {sorted(unknown)}")
        msgs = [dict(m) for m in messages]
        if not msgs or any("role" not in m or "content" not in m for m in msgs):
            raise LLMError("messages must be a non-empty list of {role, content}")

        body = {"model": endpoint.model, "messages": msgs, "stream": False}
        body["temperature"] = self._temperature(endpoint, options)
        for key in ("max_tokens", "top_p", "stop", "seed"):
            if key in options:
                body[key] = options[key]

        url = endpoint.base_url.rstrip("/") + "/chat/completions"
        record = {"kind": "llm", "role": role, "model": endpoint.model, "url": url,
                  "temperature": body["temperature"], "messages": msgs}
        started = time.monotonic()
        last: Exception | None = None
        for attempt in range(1, self._attempts + 1):
            try:
                data = self._post(url, body, endpoint)
                text, finish, usage = self._parse(data, role)
            except _Retryable as e:
                last = e
                if attempt < self._attempts:
                    delay = self._backoff * 2 ** (attempt - 1)
                    log.warning("%s call failed (%s); retry %d/%d in %.0fs", role, e, attempt, self._attempts - 1, delay)
                    self._sleep(delay)
                    continue
                err = LLMError(f"{role} model call failed after {attempt} attempts: {e}")
            except LLMError as err:
                self._record(record, started, attempt, error=str(err))
                raise
            else:
                self._record(record, started, attempt, response=text, finish_reason=finish, usage=usage)
                return text
            self._record(record, started, attempt, error=str(err))
            raise err
        raise AssertionError("unreachable")  # pragma: no cover

    # ── internals ──────────────────────────────────────────────────────────

    @staticmethod
    def _temperature(endpoint: ModelEndpoint, options: dict) -> float:
        if "temperature" in options:
            return float(options["temperature"])
        t = endpoint.temperature
        if isinstance(t, list):
            return float(t[int(options.get("draft", 0)) % len(t)])
        return float(t)

    def _post(self, url: str, body: dict, endpoint: ModelEndpoint) -> dict:
        timeout = httpx.Timeout(endpoint.timeout_seconds, connect=10.0)
        try:
            with httpx.Client(timeout=timeout, transport=self._transport) as client:
                resp = client.post(url, json=body)
        except httpx.ConnectError as e:
            raise _Retryable(f"cannot connect to {url} (is the colibri service running?): {e}") from e
        except httpx.TimeoutException as e:
            raise _Retryable(f"no reply within {endpoint.timeout_seconds:.0f}s") from e
        except httpx.TransportError as e:
            raise _Retryable(f"connection problem: {e}") from e
        if resp.status_code in RETRY_STATUS:
            raise _Retryable(f"HTTP {resp.status_code}: {resp.text[:200]}")
        if resp.status_code == 404:
            raise LLMError(f"HTTP 404 from {url}: model '{endpoint.model}' or endpoint not found: {resp.text[:200]}")
        if resp.status_code >= 400:
            raise LLMError(f"HTTP {resp.status_code} from {url}: {resp.text[:300]}")
        try:
            return resp.json()
        except ValueError as e:
            raise LLMError(f"{url} did not return JSON: {resp.text[:200]}") from e

    @staticmethod
    def _parse(data: dict, role: str) -> tuple[str, str | None, dict | None]:
        try:
            choice = data["choices"][0]
            text = choice["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise LLMError(f"{role} model returned an unexpected response shape") from e
        if not isinstance(text, str) or not text.strip():
            raise LLMError(f"{role} model returned an empty reply")
        finish = choice.get("finish_reason")
        if finish == "length":
            raise LLMError(f"{role} model reply was cut off (finish_reason=length); raise max_tokens or shorten the task")
        return text, finish, data.get("usage")

    def _record(self, record: dict, started: float, attempts: int, **extra) -> None:
        self._log.write({**record, "attempts": attempts, "duration_seconds": round(time.monotonic() - started, 3),
                         "ok": "error" not in extra, **extra})


def build_client(project) -> HttpLLMClient:
    """The real client for a project, logging to books/<book>/logs/calls.jsonl."""
    return HttpLLMClient(project.config, CallLog(project.book_dir / "logs" / "calls.jsonl"))
