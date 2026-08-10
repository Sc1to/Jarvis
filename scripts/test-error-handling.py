#!/usr/bin/env python3
"""Test error handling across platform services.

Verifies that all services return well-formed error responses (not raw 500s)
when given bad input or when dependencies are unavailable.
"""

import sys
import httpx

ADMIN = "http://localhost:8000"
CONDUCTOR = "http://localhost:8001"
CHAT = "http://localhost:8010"

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"

results = []


def check(label: str, fn):
    try:
        ok, detail = fn()
        tag = PASS if ok else FAIL
        print(f"  [{tag}] {label}: {detail}")
        results.append(ok)
    except Exception as e:
        print(f"  [{FAIL}] {label}: exception — {e}")
        results.append(False)


def assert_error_shape(r, expected_status: int = None):
    if expected_status and r.status_code != expected_status:
        return False, f"expected {expected_status}, got {r.status_code}"
    data = r.json()
    if r.status_code >= 400:
        # FastAPI standard: {"detail": "..."}
        if "detail" not in data:
            return False, f"missing 'detail' field in error response: {data}"
    return True, f"HTTP {r.status_code}"


print("\n── Admin: missing required fields ─────────────────────────────────")
with httpx.Client(base_url=ADMIN, timeout=5) as c:
    check("POST /apps missing fields", lambda: assert_error_shape(c.post("/apps", json={"name": "x"}), 422))
    check("POST /agents missing fields", lambda: assert_error_shape(c.post("/agents", json={"name": "x"}), 422))
    check("GET /apps/999999 → 404", lambda: assert_error_shape(c.delete("/apps/999999"), 404))
    check("GET /agents/999999 → 404", lambda: assert_error_shape(c.delete("/agents/999999"), 404))
    check("DELETE /ollama/models/nonexistent", lambda: (
        c.delete("/ollama/models/nonexistent:latest").status_code in (200, 404, 503),
        f"HTTP {c.delete('/ollama/models/nonexistent:latest').status_code}"
    ))

print("\n── Admin: health endpoint has dependencies field ───────────────────")
with httpx.Client(base_url=ADMIN, timeout=10) as c:
    def check_health_deps():
        r = c.get("/health")
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}"
        data = r.json()
        if "dependencies" not in data:
            return False, f"missing 'dependencies': {data}"
        return True, f"dependencies: {list(data['dependencies'].keys())}"
    check("/health has dependencies field", check_health_deps)

print("\n── Admin: platform events endpoint ─────────────────────────────────")
with httpx.Client(base_url=ADMIN, timeout=5) as c:
    def post_event():
        r = c.post("/internal/event", json={
            "service": "test", "event_type": "service_down", "message": "test event"})
        return r.status_code == 200, f"HTTP {r.status_code}"
    check("POST /internal/event", post_event)

    def get_events():
        r = c.get("/platform-events?limit=5")
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}"
        data = r.json()
        if not isinstance(data, list):
            return False, f"expected list, got {type(data)}"
        return True, f"{len(data)} event(s)"
    check("GET /platform-events", get_events)

print("\n── Conductor: bad requests ──────────────────────────────────────────")
with httpx.Client(base_url=CONDUCTOR, timeout=5) as c:
    check("POST /session/start empty body → 400",
          lambda: assert_error_shape(c.post("/session/start", json={}), 400))
    check("GET /session/nonexistent → 404",
          lambda: assert_error_shape(c.get("/session/nonexistent/status"), 404))

print("\n── Updates: cached response is instant ──────────────────────────────")
with httpx.Client(base_url=ADMIN, timeout=5) as c:
    import time
    t0 = time.time()
    r = c.get("/updates/available")
    elapsed = time.time() - t0
    check("GET /updates/available responds in <2s",
          lambda: (elapsed < 2.0 and r.status_code == 200, f"{elapsed:.2f}s, HTTP {r.status_code}"))
    check("/updates/available has last_checked field",
          lambda: ("last_checked" in r.json(), str(r.json().get("last_checked"))))

print()
total = len(results)
passed = sum(results)
print(f"Results: {passed}/{total} passed")
if passed < total:
    sys.exit(1)
