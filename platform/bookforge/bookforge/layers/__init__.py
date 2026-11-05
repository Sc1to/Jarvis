"""Layer handlers, one per pipeline layer.

TODO: replace with real implementation. Handlers for layers 1-3 arrive in
milestone 14.3, layers 4-6 in 14.5, prose in 14.6 (see BUILD_SEQUENCE.md, Phase 14).
Until then the registry is empty and `run` stops at the first layer it cannot run.
"""

from .runner import Handler

HANDLERS: dict[str, Handler] = {}
