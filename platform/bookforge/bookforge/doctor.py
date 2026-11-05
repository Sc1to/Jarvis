"""`doctor`: environment checks.

Local checks always run. Unless `online=False` (`--offline`), it also checks the two
colibri endpoints (GET <base_url>/models), the System One endpoint, and the platform
web tool, including one real page fetch through it.
"""

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx

from . import vcs
from .config import Config, ModelEndpoint, host_config_path, load_config
from .errors import BookforgeError
from .research.search import PlaywrightWebClient, WebClient, WebError, load_web_tool_class, playwright_installed
from .state import load_state

TEST_PAGE = "https://example.com"
PROBE_TIMEOUT = 5.0


@dataclass
class Check:
    name: str
    level: str  # pass | warn | fail
    detail: str = ""


def check_models_endpoint(role: str, endpoint: ModelEndpoint, transport: httpx.BaseTransport | None = None) -> Check:
    name = f"endpoint_{role}"
    url = endpoint.base_url.rstrip("/") + "/models"
    unit = f"platform-colibri-{role}"
    try:
        with httpx.Client(timeout=httpx.Timeout(PROBE_TIMEOUT), transport=transport) as client:
            resp = client.get(url)
    except httpx.HTTPError as e:
        return Check(name, "fail", f"cannot reach {url} (is {unit} running?): {e}")
    if resp.status_code != 200:
        return Check(name, "fail", f"{url} returned HTTP {resp.status_code}")
    try:
        ids = [m["id"] for m in resp.json()["data"]]
    except (ValueError, KeyError, TypeError):
        return Check(name, "fail", f"{url} did not return an OpenAI-style model list")
    if not endpoint.model:
        return Check(name, "warn", f"reachable; set models.{role}.model to one of: {', '.join(ids) or '(none listed)'}")
    if endpoint.model not in ids:
        return Check(name, "fail", f"model '{endpoint.model}' is not served at {url} (available: {', '.join(ids) or 'none'})")
    return Check(name, "pass", f"{url} serves {endpoint.model}")


def check_decide_endpoint(url: str, transport: httpx.BaseTransport | None = None) -> Check:
    try:
        with httpx.Client(timeout=httpx.Timeout(PROBE_TIMEOUT), transport=transport) as client:
            resp = client.get(url)
    except httpx.HTTPError as e:
        return Check("endpoint_decide", "warn", f"cannot reach {url}: {e}. Not used yet: continuity questions are answered by the planner model")
    if resp.status_code < 300:
        return Check("endpoint_decide", "pass", f"{url} answered HTTP {resp.status_code} (not used yet: continuity questions are answered by the planner model)")
    return Check("endpoint_decide", "warn", f"{url} answered HTTP {resp.status_code}; System One support is unverified (not used yet: continuity questions are answered by the planner model)")


def check_web(web_client: WebClient | None = None, fetch: bool = True) -> list[Check]:
    checks: list[Check] = []
    try:
        load_web_tool_class()
        checks.append(Check("web_tool", "pass", "platform/tools/web_tool.py importable"))
    except WebError as e:
        return [Check("web_tool", "fail", str(e))]
    if web_client is None and not playwright_installed():
        checks.append(Check("playwright", "fail", "not installed (pip install playwright; playwright install chromium)"))
        return checks
    if web_client is None:
        checks.append(Check("playwright", "pass", "installed"))
        web_client = PlaywrightWebClient(attempts=1)
    if fetch:
        try:
            result = web_client.fetch(TEST_PAGE)
            checks.append(Check("web_fetch", "pass", f"fetched {TEST_PAGE} ({len(result.text)} chars)"))
        except BookforgeError as e:
            checks.append(Check("web_fetch", "fail", str(e)))
    return checks


def run_doctor(
    series: Path | None = None,
    book: str = "b1",
    online: bool = True,
    transport: httpx.BaseTransport | None = None,
    web_client: WebClient | None = None,
) -> list[Check]:
    checks: list[Check] = []

    v = sys.version_info
    checks.append(Check(
        "python", "pass" if v[:2] >= (3, 12) else "warn",
        f"{v.major}.{v.minor}.{v.micro}" + ("" if v[:2] >= (3, 12) else " (Jarvis targets 3.12)"),
    ))

    git = shutil.which("git")
    checks.append(Check("git", "pass" if git else "fail", git or "git not found on PATH"))

    config: Config | None = None
    try:
        config = load_config(series)
        host = host_config_path()
        checks.append(Check("config", "pass", f"valid ({host if host else 'built-in defaults'})"))
    except BookforgeError as e:
        checks.append(Check("config", "fail", str(e)))

    if config is not None:
        data_dir = Path(config.data_dir)
        if not data_dir.exists():
            checks.append(Check("data_dir", "warn", f"{data_dir} does not exist yet"))
        elif os.access(data_dir, os.W_OK):
            checks.append(Check("data_dir", "pass", str(data_dir)))
        else:
            checks.append(Check("data_dir", "fail", f"{data_dir} is not writable"))

        if not online:  # online, the endpoint checks report the model ids
            for role in ("writer", "critic"):
                m = getattr(config.models, role)
                if m.model:
                    checks.append(Check(f"model_{role}", "pass", m.model))
                else:
                    checks.append(Check(f"model_{role}", "warn", f"models.{role}.model not set (see `c/coli status`)"))

    if series is not None:
        try:
            state = load_state(series / "books" / book / "state.json")
            checks.append(Check("series_state", "pass", f"book {state.book}"))
        except BookforgeError as e:
            checks.append(Check("series_state", "fail", str(e)))
        else:
            if not vcs.is_repo(series):
                checks.append(Check("series_git", "fail", "not a git repository"))
            elif vcs.is_dirty(series):
                checks.append(Check("series_git", "warn", "uncommitted changes in the series"))
            else:
                checks.append(Check("series_git", "pass", "clean"))

    if config is not None:
        if online:
            checks.append(check_models_endpoint("writer", config.models.writer, transport))
            checks.append(check_models_endpoint("critic", config.models.critic, transport))
            checks.append(check_decide_endpoint(config.models.decide.url, transport))
            checks.extend(check_web(web_client))
        else:
            checks.append(Check("network", "warn", "endpoint and web checks skipped (--offline)"))
            checks.extend(check_web(web_client, fetch=False))
    return checks
