"""Shared mutable prompt store for all writer agents. Admin pushes overrides here at runtime."""
_store: dict[str, str] = {}


def get(key: str, default: str) -> str:
    return _store.get(key, default)


def set_(key: str, value: str) -> None:
    _store[key] = value


def all_effective(defaults: dict[str, str]) -> dict[str, str]:
    return {k: _store.get(k, v) for k, v in defaults.items()}
