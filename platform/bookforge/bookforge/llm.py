"""LLM client: the interface, the real OpenAI-compatible client, and a fake for tests.

All model calls in bookforge go through an object with the `LLMClient` interface.
The real client talks to the two colibri servers (config `models.writer` and
`models.critic`), retries transient failures, and logs every call to
books/<book>/logs/calls.jsonl.
"""

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Protocol, Sequence

import httpx

from . import activity, cancel
from .calllog import CallLog
from .config import Config, ModelEndpoint
from .errors import BookforgeError

log = logging.getLogger("platform_bookforge.llm")

Messages = Sequence[dict]

# Options a caller may pass through to the server, plus `draft` (picks the temperature).
ALLOWED_OPTIONS = {"temperature", "max_tokens", "top_p", "stop", "seed", "draft", "grow"}  # draft and grow are ours, not sent to the server
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


def _isolated(messages: list[dict]) -> list[dict]:
    """The messages with a unique first line in the system message.

    Found on the first real run: with Ollama, a request that began with the same words as the previous one (the
    shared system prompt) was answered as if it were that previous request: JSON about the wrong topic, in the
    wrong format. A unique start means there is nothing for the server to reuse. The log keeps the original messages.
    """
    tag = f"Request {uuid.uuid4().hex[:12]}."
    out = [dict(m) for m in messages]
    if out[0]["role"] == "system":
        out[0]["content"] = f"{tag}\n\n{out[0]['content']}"
    else:
        out.insert(0, {"role": "system", "content": tag})
    return out


class LLMError(BookforgeError):
    """A model call failed for good (after retries, or not worth retrying)."""


REPEAT_WORDS = 8  # a run of this many words
REPEATING = 0.4  # at least this share of a cut-off reply made of repeated runs: the model is stuck repeating itself


def repeated_share(text: str) -> float:
    """The share of the text's runs of 8 words that occur more than once: near 0 for prose, high for a model stuck in a loop."""
    words = text.split()
    runs = [" ".join(words[i:i + REPEAT_WORDS]) for i in range(len(words) - REPEAT_WORDS + 1)]
    if not runs:
        return 0.0
    counts: dict[str, int] = {}
    for r in runs:
        counts[r] = counts.get(r, 0) + 1
    return sum(c for c in counts.values() if c > 1) / len(runs)


class TruncatedReply(LLMError):
    """The model stopped because it ran out of tokens (finish_reason=length), so the reply is incomplete."""

    def __init__(self, message: str, tail: str = "", chars: int = 0, repeated: float = 0.0):
        super().__init__(message)
        self.tail, self.chars, self.repeated = tail, chars, repeated

    @property
    def repeating(self) -> bool:
        return self.repeated >= REPEATING

    def extras(self) -> dict:
        """What the call log keeps about the cut-off reply, so a repeating model can be told from a merely long reply."""
        return {"response_chars": self.chars, "response_tail": self.tail, "repeated_share": round(self.repeated, 3)}


class _Retryable(Exception):
    pass


# A reply cut off at its token limit is asked for again with a larger limit (doubled, at least +1000), up to this many times and
# never above the cap. The limits the callers pass are estimates from word counts; models vary in how many tokens a word takes.
TRUNCATION_RETRIES = 2
MAX_TOKENS_CAP = 16000


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
        """The model's reply. A reply cut off at its token limit is asked for again with a larger limit before it counts as a failure."""
        limit = options.get("max_tokens")
        may_grow = options.get("grow", True)
        for grown in range(TRUNCATION_RETRIES + 1):
            try:
                return self._complete(role, messages, **options)
            except TruncatedReply as e:
                # A model that is repeating itself will repeat itself at any limit, and a caller that knows its reply has a hard
                # maximum (a scene) does not want a longer one: neither is asked again with more tokens.
                if (not may_grow or e.repeating or not isinstance(limit, int) or limit >= MAX_TOKENS_CAP or grown == TRUNCATION_RETRIES):
                    first = next((m["content"] for m in reversed(list(messages)) if m.get("role") == "user"), "")
                    why = (f"the model is repeating itself ({e.repeated:.0%} of the reply is repeated text)" if e.repeating
                           else "the reply is longer than this call allows" if not may_grow else f"even after raising the limit {grown} time(s)")
                    raise TruncatedReply(
                        f"{role} model reply was cut off at {limit} tokens (finish_reason=length): {why}. "
                        f"The prompt began: {' '.join(str(first).split())[:90]!r}",
                        tail=e.tail, chars=e.chars, repeated=e.repeated) from e
                bigger = min(MAX_TOKENS_CAP, max(limit * 2, limit + 1000))
                log.warning("%s reply cut off at %d tokens; asking again with %d", role, limit, bigger)
                limit = bigger
                options = {**options, "max_tokens": bigger}
        raise AssertionError("unreachable")  # pragma: no cover

    def _complete(self, role: str, messages: Messages, **options) -> str:
        cancel.check()  # the author stopped the job: stop before asking the model again
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

        body = {**endpoint.extra_body, "model": endpoint.model,
                "messages": _isolated(msgs) if endpoint.isolate_requests else msgs, "stream": False}
        body["temperature"] = self._temperature(endpoint, options)
        for key in ("max_tokens", "top_p", "stop", "seed"):
            if key in options:
                body[key] = options[key]

        url = endpoint.base_url.rstrip("/") + "/chat/completions"
        record = {"kind": "llm", "role": role, "model": endpoint.model, "url": url,
                  "temperature": body["temperature"], "messages": msgs}
        if endpoint.extra_body:
            record["extra_body"] = endpoint.extra_body
        started = time.monotonic()
        last: Exception | None = None
        label = next((m["content"] for m in reversed(msgs) if m.get("role") == "user"), "")
        for attempt in range(1, self._attempts + 1):
            try:
                activity.call_started(role, str(label))
                try:
                    data = self._post(url, body, endpoint)
                finally:
                    activity.call_finished()
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
                self._record(record, started, attempt, error=str(err), **(err.extras() if isinstance(err, TruncatedReply) else {}))
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
            message = choice.get("message") or {}
            if message.get("reasoning") or message.get("reasoning_content"):
                raise LLMError(f"{role} model returned only its thinking and no reply"
                               + (" (it ran out of tokens while thinking)" if choice.get("finish_reason") == "length" else "")
                               + f": set models.{role}.extra_body to {{reasoning_effort: none}} (or give it a larger token budget)")
            raise LLMError(f"{role} model returned an empty reply")
        finish = choice.get("finish_reason")
        if finish == "length":
            raise TruncatedReply(f"{role} model reply was cut off (finish_reason=length); raise max_tokens or shorten the task",
                                 tail=text.strip()[-300:], chars=len(text), repeated=repeated_share(text))
        return text, finish, data.get("usage")

    def _record(self, record: dict, started: float, attempts: int, **extra) -> None:
        self._log.write({**record, "attempts": attempts, "duration_seconds": round(time.monotonic() - started, 3),
                         "ok": "error" not in extra, **extra})


def build_client(project) -> HttpLLMClient:
    """The real client for a project, logging to books/<book>/logs/calls.jsonl."""
    return HttpLLMClient(project.config, CallLog(project.book_dir / "logs" / "calls.jsonl"))
