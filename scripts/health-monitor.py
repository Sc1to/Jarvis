#!/usr/bin/env python3
"""Health monitor daemon — polls registered services every 30s, restarts on failure."""

import json
import logging
import sqlite3
import subprocess
import time
from contextlib import contextmanager

import httpx

DB_PATH = "/opt/platform/data/platform.db"
ADMIN_URL = "http://localhost:8000"
POLL_INTERVAL = 30
UPDATE_INTERVAL = 3600

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

_down: set[str] = set()


@contextmanager
def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _post_event(service: str, event_type: str, message: str, metadata: dict = None):
    try:
        httpx.post(
            f"{ADMIN_URL}/internal/event",
            json={"service": service, "event_type": event_type,
                  "message": message, "metadata": metadata or {}},
            timeout=5,
        )
    except Exception as e:
        log.warning("Could not post event: %s", e)


def _services():
    with _db() as conn:
        rows = conn.execute(
            "SELECT name, backend_port FROM apps WHERE backend_port IS NOT NULL AND status='active'"
        ).fetchall()
    return [dict(r) for r in rows]


def _up(port: int) -> bool:
    try:
        r = httpx.get(f"http://localhost:{port}/health", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def _restart(name: str) -> bool:
    svc = f"platform-{name.lower().replace(' ', '-')}"
    try:
        subprocess.run(["sudo", "systemctl", "restart", svc], check=True, timeout=15)
        log.info("Restarted %s", svc)
        return True
    except Exception as e:
        log.error("Restart failed for %s: %s", svc, e)
        return False


def _check_updates():
    try:
        subprocess.run(["sudo", "apt-get", "update", "-qq"], timeout=60, capture_output=True)
        r = subprocess.run(["apt", "list", "--upgradable", "--quiet"],
            capture_output=True, text=True, timeout=15)
        lines = [l for l in r.stdout.splitlines() if "/" in l and "upgradable" not in l.lower()]
        result = json.dumps({"packages": lines, "count": len(lines)})
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        with _db() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO config (key, value) VALUES ('pending_updates_json', ?)", (result,))
            conn.execute(
                "INSERT OR REPLACE INTO config (key, value) VALUES ('last_update_check', ?)", (now,))
        log.info("Update check: %d package(s) pending", len(lines))
        if lines:
            _post_event("system", "updates_available", f"{len(lines)} package(s) available",
                        {"count": len(lines)})
    except Exception as e:
        log.error("Update check failed: %s", e)


def poll():
    for svc in _services():
        name, port = svc["name"], svc["backend_port"]
        if _up(port):
            if name in _down:
                _down.discard(name)
                log.info("%s recovered", name)
                _post_event(name, "service_recovered", f"{name} is back online")
        else:
            if name not in _down:
                _down.add(name)
                log.warning("%s is down — attempting restart", name)
                _post_event(name, "service_down", f"{name} (port {port}) not responding")
                if _restart(name):
                    time.sleep(5)
                    if _up(port):
                        _down.discard(name)
                        _post_event(name, "service_recovered", f"{name} recovered after restart")
                    else:
                        _post_event(name, "restart_failed", f"{name} did not recover after restart")


def main():
    log.info("Health monitor started (poll=%ds, update_check=%dh)", POLL_INTERVAL, UPDATE_INTERVAL // 3600)
    last_update_check = 0
    while True:
        try:
            poll()
        except Exception as e:
            log.error("Poll error: %s", e)
        if time.time() - last_update_check > UPDATE_INTERVAL:
            _check_updates()
            last_update_check = time.time()
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
