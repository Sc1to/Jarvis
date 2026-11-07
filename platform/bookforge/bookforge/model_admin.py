"""Which models are running, which are available, and which one each role and layer uses.

Read-only for colibri (its server runs one model chosen at start; switching means restarting its unit, which bookforge does not do):
what it serves is shown and can be assigned to a role. Ollama models can be assigned freely; the model a role leaves behind is
unloaded so only the ones in use stay in memory.

Choices are saved in `<series>/models.local.yaml`, which `load_config` merges last. The file is written by bookforge only (no
comments to lose); `config.yaml` stays yours.
"""

import logging
import re
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import yaml

from .config import LOCAL_CHOICES_FILE, Config, ModelEndpoint, load_config
from .errors import BookforgeError, ConfigError

log = logging.getLogger("platform_bookforge.model_admin")

LOCAL_FILE = LOCAL_CHOICES_FILE
OLLAMA_DEFAULT = "http://127.0.0.1:11434/v1"
PROBE_TIMEOUT = 5.0
GB = 1024 ** 3
MEMORY_MARGIN = 1.2  # a model needs its weights plus room for the context (KV cache)
DIRECT = ("writer", "critic")  # targets that set an endpoint's own model; the others point a name at an endpoint
ASSIGNED = ("research", "extraction", "qc", "notes")


class ModelChoiceError(BookforgeError):
    pass


def backend_of(base_url: str) -> str:
    """ollama (port 11434) or colibri (anything else: bookforge's own servers)."""
    return "ollama" if urlsplit(base_url).port == 11434 else "colibri"


def _root(base_url: str) -> str:
    u = urlsplit(base_url)
    return f"{u.scheme}://{u.netloc}"


def memory() -> dict:
    """RAM of the machine, from /proc/meminfo (empty off Linux). The MS-S1 Max shares it with the GPU."""
    try:
        info: dict[str, int] = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":", 1)
                info[k] = int(v.split()[0])
        return {"total_gb": round(info["MemTotal"] / 1048576, 1), "available_gb": round(info["MemAvailable"] / 1048576, 1)}
    except (OSError, KeyError, ValueError):
        return {}


def _get(client: httpx.Client, url: str) -> httpx.Response | None:
    try:
        return client.get(url)
    except httpx.HTTPError:
        return None


def probe(base_url: str, transport: httpx.BaseTransport | None = None) -> dict:
    """What one backend serves right now: {base_url, backend, reachable, state, error, models: [{id, size_gb, loaded}]}."""
    backend = backend_of(base_url)
    out: dict = {"base_url": base_url, "backend": backend, "reachable": False, "state": "down", "error": "", "models": []}
    root = _root(base_url)
    with httpx.Client(timeout=httpx.Timeout(PROBE_TIMEOUT), transport=transport) as client:
        if backend == "ollama":
            tags, ps = _get(client, root + "/api/tags"), _get(client, root + "/api/ps")
            if tags is None or tags.status_code != 200:
                out["error"] = f"cannot reach {root}/api/tags (is Ollama running?)"
                return out
            try:
                loaded = {m["name"] for m in ps.json().get("models", [])} if ps is not None and ps.status_code == 200 else set()
                out["models"] = [{"id": m["name"], "size_gb": round(m.get("size", 0) / GB, 1), "loaded": m["name"] in loaded}
                                 for m in tags.json().get("models", [])]
            except (ValueError, KeyError, TypeError, AttributeError):
                out["error"] = f"{root} did not answer like Ollama"
                return out
            out.update(reachable=True, state="ready")
            return out
        health, listing = _get(client, root + "/health"), _get(client, base_url.rstrip("/") + "/models")
    if health is not None and health.status_code == 503:
        out.update(reachable=True, state="loading", error="the engine is starting (a large model can take a long time to load)")
        return out
    if listing is None or listing.status_code != 200:
        out["error"] = f"cannot reach {base_url.rstrip('/')}/models (is the colibri unit running?)"
        return out
    try:
        ids = [m["id"] for m in listing.json()["data"]]
    except (ValueError, KeyError, TypeError):
        out["error"] = f"{base_url} did not return an OpenAI-style model list"
        return out
    out["models"] = [{"id": i, "size_gb": None, "loaded": True} for i in ids]  # a colibri server serves only what it loaded
    out.update(reachable=True, state="ready")
    return out


def _endpoint_urls(config: Config) -> list[str]:
    urls: list[str] = []
    for name in ("writer", "critic", *config.models.extra):
        u = config.endpoint(name).base_url
        if u not in urls:
            urls.append(u)
    if OLLAMA_DEFAULT not in urls:
        urls.append(OLLAMA_DEFAULT)
    return urls


def _layers_using(config: Config) -> dict[str, list[str]]:
    used: dict[str, list[str]] = {}
    for layer, s in config.layers.items():
        used.setdefault(s.model, []).append(layer)
    return used


def overview(config: Config, transport: httpx.BaseTransport | None = None) -> dict:
    """Everything the Models page shows."""
    probes = {u: probe(u, transport) for u in _endpoint_urls(config)}
    ram = memory()
    loaded_gb = sum(m["size_gb"] or 0 for p in probes.values() if p["backend"] == "ollama" for m in p["models"] if m["loaded"])
    free_gb = (ram.get("available_gb", 0) + loaded_gb) if ram else None  # loaded Ollama models are unloaded on a switch
    available = []
    for p in probes.values():
        for m in p["models"]:
            warning = ""
            if p["backend"] == "ollama" and free_gb is not None and m["size_gb"] and not m["loaded"]:
                need = round(m["size_gb"] * MEMORY_MARGIN, 1)
                if need > free_gb:
                    warning = f"needs about {need} GB with room for the context; about {round(free_gb, 1)} GB would be free"
            available.append({"base_url": p["base_url"], "backend": p["backend"], "id": m["id"], "size_gb": m["size_gb"],
                              "loaded": m["loaded"], "warning": warning})
    using = _layers_using(config)
    names = []
    for name in config.model_names():
        ep = config.endpoint(name)
        p = probes.get(ep.base_url, {})
        entry = next((m for m in p.get("models", []) if m["id"] in (ep.model, f"{ep.model}:latest")), None)
        names.append({
            "name": name, "base_url": ep.base_url, "model": ep.model, "backend": backend_of(ep.base_url),
            "state": p.get("state", "down"), "loaded": bool(entry and entry["loaded"]), "installed": entry is not None,
            "is_alias": name in ("research", "extraction"), "layers": using.get(name, []),
            "manage_service": ep.manage_service,
        })
    return {
        "names": names, "backends": list(probes.values()), "available": available, "memory": ram,
        "layers": {layer: s.model for layer, s in config.layers.items()},
        "assign": {"research": config.models.assign.research, "extraction": config.models.assign.extraction,
                   "qc": config.qc.model, "notes": config.research.notes_model},
    }


# ── choices ──────────────────────────────────────────────────────────────────

def local_path(series_root: Path) -> Path:
    return series_root / LOCAL_FILE


def read_local(series_root: Path) -> dict:
    p = local_path(series_root)
    if not p.exists():
        return {}
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as e:
        raise ConfigError(f"cannot read {p}: {e}") from e
    if not isinstance(data, dict):
        raise ConfigError(f"{p} must contain a mapping at the top level")
    return data


def _write_local(series_root: Path, data: dict) -> None:
    text = "# Written by the bookforge dashboard (Models). Edit config.yaml for anything else.\n" + yaml.safe_dump(data, sort_keys=True, allow_unicode=True)
    local_path(series_root).write_text(text, encoding="utf-8")


def _slug(model: str) -> str:
    return re.sub(r"[^a-z0-9._-]+", "-", model.lower()).strip("-") or "model"


def _name_for(config: Config, local: dict, base_url: str, model: str) -> str:
    """A name whose endpoint is exactly this model; a new `extra` endpoint if none is."""
    for name in ("writer", "critic", *config.models.extra):
        ep = config.endpoint(name)
        if ep.base_url == base_url and ep.model == model:
            return name
    name = _slug(model)
    if name in ("writer", "critic", "research", "extraction") or (name in config.models.extra and config.endpoint(name).base_url != base_url):
        name = f"{name}-{backend_of(base_url)}"
    donor = next((config.endpoint(n) for n in ("writer", "critic", *config.models.extra) if config.endpoint(n).base_url == base_url), None)
    ep = ModelEndpoint(base_url=base_url, model=model, temperature=0.2, timeout_seconds=donor.timeout_seconds if donor else 600,
                       isolate_requests=donor.isolate_requests if donor else True, extra_body=dict(donor.extra_body) if donor else {})
    local.setdefault("models", {}).setdefault("extra", {})[name] = ep.model_dump(mode="json", exclude_none=True)
    return name


def choose(series_root: Path, target: str, base_url: str | None, model: str | None,
           transport: httpx.BaseTransport | None = None) -> dict:
    """Give a role or layer another model. `target`: writer | critic | research | extraction | qc | notes | layer:<name>.
    No base_url/model for a layer puts it back on its default. Returns the new overview plus what was done."""
    config = load_config(series_root)
    local = read_local(series_root)
    before = {n: (config.endpoint(n).base_url, config.endpoint(n).model) for n in config.model_names()}
    is_layer = target.startswith("layer:")
    layer = target[6:] if is_layer else ""
    if is_layer and layer not in config.layers:
        raise ModelChoiceError(f"unknown layer '{layer}'")
    if not is_layer and target not in DIRECT + ASSIGNED:
        raise ModelChoiceError(f"unknown target '{target}'")

    notes: list[str] = []
    if base_url is None and model is None:
        if not is_layer:
            raise ModelChoiceError("choose a model")
        (local.get("layers") or {}).pop(layer, None)
        if "layers" in local and not local["layers"]:
            del local["layers"]
    else:
        if not base_url or not model:
            raise ModelChoiceError("both the backend and the model are needed")
        # Only a model a configured backend lists can be chosen: the page cannot point bookforge at any address.
        if not any(a["base_url"] == base_url and a["id"] == model for a in overview(config, transport)["available"]):
            raise ModelChoiceError(f"'{model}' is not served at {base_url} right now")
        if target in DIRECT:
            old = config.endpoint(target)
            ep = old.model_copy(update={"base_url": base_url, "model": model})
            if old.base_url != base_url:
                ep = ep.model_copy(update={"extra_body": {}})
                if old.extra_body:
                    notes.append(f"the extra request fields set for {target} ({', '.join(old.extra_body)}) were dropped: they belong to the old backend")
            local.setdefault("models", {})[target] = ep.model_dump(mode="json", exclude_none=True)
        else:
            name = _name_for(config, local, base_url, model)
            if is_layer:
                local.setdefault("layers", {}).setdefault(layer, {})["model"] = name
            elif target in ("research", "extraction"):
                local.setdefault("models", {}).setdefault("assign", {})[target] = name
            elif target == "qc":
                local.setdefault("qc", {})["model"] = name
            else:
                local.setdefault("research", {})["notes_model"] = name

    previous = local_path(series_root).read_text(encoding="utf-8") if local_path(series_root).exists() else None
    _write_local(series_root, local)
    try:
        new = load_config(series_root)
    except BookforgeError:
        if previous is None:
            local_path(series_root).unlink(missing_ok=True)
        else:
            local_path(series_root).write_text(previous, encoding="utf-8")
        raise

    unloaded = _unload_unused(before, new, transport)
    return {**overview(new, transport), "notes": notes, "unloaded": unloaded}


def _unload_unused(before: dict, new: Config, transport: httpx.BaseTransport | None) -> list[str]:
    """Ollama keeps a model in memory for minutes after its last request: unload the ones no role uses any more."""
    in_use = {(new.endpoint(n).base_url, new.endpoint(n).model) for n in new.model_names()}
    gone = {pair for pair in before.values() if pair not in in_use and pair[1] and backend_of(pair[0]) == "ollama"}
    done: list[str] = []
    for base_url, model in sorted(gone):
        try:
            with httpx.Client(timeout=httpx.Timeout(PROBE_TIMEOUT), transport=transport) as client:
                r = client.post(_root(base_url) + "/api/generate", json={"model": model, "keep_alive": 0})
            if r.status_code == 200:
                done.append(model)
        except httpx.HTTPError as e:
            log.warning("could not unload %s: %s", model, e)
    return done
