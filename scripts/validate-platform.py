#!/usr/bin/env python3
"""
validate-platform.py — Platform health check

Run on the mini PC at any time to get a pass/fail report of every platform service.
No external dependencies — uses stdlib only.

Usage: python3 scripts/validate-platform.py
"""

import json
import subprocess
import sys
import urllib.error
import urllib.request

PASS = "✓"
FAIL = "✗"
_results = []


def check(name, ok, detail=""):
    icon = PASS if ok else FAIL
    msg = f"  {icon} {name}"
    if detail:
        msg += f"  ({detail})"
    print(msg)
    _results.append(ok)
    return ok


def systemctl_active(service):
    r = subprocess.run(["systemctl", "is-active", "--quiet", service])
    return r.returncode == 0


def http_get(url, timeout=5):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception:
        return None, ""


# ── Tailscale ─────────────────────────────────────────────────────────────────
print("\nTailscale")
check("tailscaled running", systemctl_active("tailscaled"))

# ── Caddy ─────────────────────────────────────────────────────────────────────
print("\nCaddy")
check("caddy running", systemctl_active("caddy"))
status, _ = http_get("http://localhost:80")
check("responding on :80", status is not None, f"HTTP {status}" if status else "no response")

# ── Ollama ────────────────────────────────────────────────────────────────────
print("\nOllama")
check("ollama running", systemctl_active("ollama"))
status, body = http_get("http://localhost:11434/api/tags")
if status == 200:
    try:
        models = {m["name"] for m in json.loads(body).get("models", [])}
    except Exception:
        models = set()
    check("API responding", True, f"{len(models)} model(s) available")
    for name in ["qwen2.5:14b", "qwen2.5-coder:32b", "qwen2.5:72b-instruct-q4_K_M"]:
        check(f"model present: {name}", any(name in m for m in models))
else:
    check("API responding", False, "Ollama may not be running")
    for name in ["qwen2.5:14b", "qwen2.5-coder:32b", "qwen2.5:72b-instruct-q4_K_M"]:
        check(f"model present: {name}", False, "skipped")

# ── Chat backend ──────────────────────────────────────────────────────────────
print("\nChat backend  (port 8010)")
check("platform-chat running", systemctl_active("platform-chat"))
status, body = http_get("http://localhost:8010/health")
if status == 200:
    try:
        d = json.loads(body)
        check("/health OK", d.get("status") == "ok",
              f"v{d.get('version', '?')}  up {d.get('uptime_seconds', '?')}s")
    except Exception:
        check("/health OK", False, "unparseable response")
else:
    check("/health OK", False, f"HTTP {status}" if status else "no response")

# ── Chat frontend ─────────────────────────────────────────────────────────────
print("\nChat frontend  (/chat)")
status, body = http_get("http://localhost/chat/", timeout=5)
check("served at /chat/", status == 200, f"HTTP {status}" if status else "no response")

# ── End-to-end ────────────────────────────────────────────────────────────────
print("\nEnd-to-end")
try:
    payload = json.dumps({
        "message": "Reply with one word: OK",
        "model": "qwen2.5:14b",
        "history": [],
    }).encode()
    req = urllib.request.Request(
        "http://localhost:8010/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    content = ""
    with urllib.request.urlopen(req, timeout=60) as r:
        for raw_line in r:
            line = raw_line.decode().strip()
            if not line.startswith("data: "):
                continue
            try:
                chunk = json.loads(line[6:])
                if chunk.get("error"):
                    content = f"[error] {chunk['error']}"
                    break
                content += chunk.get("message", {}).get("content", "")
                if chunk.get("done"):
                    break
            except json.JSONDecodeError:
                pass
    check("chat API round-trip", bool(content), repr(content[:60]))
except Exception as e:
    check("chat API round-trip", False, str(e)[:80])

# ── Summary ───────────────────────────────────────────────────────────────────
passed = sum(_results)
total = len(_results)
print(f"\n{'─' * 42}")
print(f"  {passed}/{total} checks passed")
if passed == total:
    print("  Platform is healthy.\n")
else:
    failed = total - passed
    print(f"  {failed} check(s) failed — review output above.\n")
    sys.exit(1)
