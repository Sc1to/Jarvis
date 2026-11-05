"""LLM client interface and the fake used by tests.

All model calls in bookforge go through an object with this interface. The real
OpenAI-compatible client (retries, logging to logs/calls.jsonl) arrives in
milestone 14.2.
"""

from dataclasses import dataclass, field
from typing import Callable, Protocol, Sequence

Messages = Sequence[dict]


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
