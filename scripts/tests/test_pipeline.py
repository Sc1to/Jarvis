"""Autocoder pipeline integration test — start session, poll completion, verify output."""
import time
import httpx

CONDUCTOR_PORT = 8001
DASHBOARD_PORT = 8050
POLL_INTERVAL  = 10   # seconds between polls
TIMEOUT        = 300  # 5 minutes max

# Minimal requirements doc — quick to process, no ambiguity
TEST_REQUIREMENTS = """
## Test Session — GET /ping endpoint

Implement a FastAPI app with a single endpoint:
  GET /ping → returns {"pong": true}

Requirements:
- Single file: main.py
- Uses FastAPI and uvicorn
- /ping returns JSON {"pong": true} with HTTP 200
""".strip()


def run(base_url: str) -> tuple[int, int]:
    conductor = f"{base_url}:{CONDUCTOR_PORT}"
    dashboard = f"{base_url}:{DASHBOARD_PORT}"
    passed = failed = 0

    # ── Start session ─────────────────────────────────────────────────────────

    print("  Starting test pipeline session...")
    try:
        r = httpx.post(f"{conductor}/session/start", json={
            "project_name": f"__test_pipeline_{int(time.time())}",
            "requirements": TEST_REQUIREMENTS,
        }, timeout=30)
    except Exception as exc:
        print(f"  \033[31m[FAIL]\033[0m  session/start unreachable: {exc}")
        return 0, 5

    if r.status_code != 200:
        print(f"  \033[31m[FAIL]\033[0m  session/start returned {r.status_code}")
        return 0, 5

    session_id = r.json().get("session_id")
    print(f"         session_id: {session_id}")
    passed += 1

    # ── Poll for completion ───────────────────────────────────────────────────

    deadline = time.time() + TIMEOUT
    outcome = None
    while time.time() < deadline:
        try:
            r = httpx.get(f"{dashboard}/sessions/{session_id}", timeout=10)
            data = r.json()
            status = data.get("status")
            if status in ("success", "failed", "parked"):
                outcome = status
                break
            print(f"         status: {status} — waiting {POLL_INTERVAL}s...")
        except Exception:
            pass
        time.sleep(POLL_INTERVAL)

    if outcome is None:
        print(f"  \033[31m[FAIL]\033[0m  session timed out after {TIMEOUT}s")
        return passed, failed + 4

    if outcome in ("success", "parked"):
        print(f"  \033[32m[PASS]\033[0m  session completed with outcome: {outcome}")
        passed += 1
    else:
        print(f"  \033[31m[FAIL]\033[0m  session outcome: {outcome}")
        failed += 1

    # ── Verify events logged ──────────────────────────────────────────────────

    try:
        r = httpx.get(f"{dashboard}/sessions/{session_id}/events", timeout=10)
        events = r.json()
        if events:
            print(f"  \033[32m[PASS]\033[0m  {len(events)} events logged in dashboard")
            passed += 1
        else:
            print(f"  \033[31m[FAIL]\033[0m  no events logged")
            failed += 1
    except Exception as exc:
        print(f"  \033[31m[FAIL]\033[0m  events API: {exc}")
        failed += 1

    # ── Verify at least one git commit ────────────────────────────────────────

    try:
        r = httpx.get(f"{dashboard}/projects/{session_id}/commits", timeout=10)
        commits = r.json()
        if commits:
            print(f"  \033[32m[PASS]\033[0m  {len(commits)} commit(s) created")
            passed += 1
        else:
            print(f"  \033[31m[FAIL]\033[0m  no commits created")
            failed += 1
    except Exception as exc:
        print(f"  \033[31m[FAIL]\033[0m  commits API: {exc}")
        failed += 1

    return passed, failed


if __name__ == "__main__":
    p, f = run("http://localhost")
    print(f"\n{p} passed, {f} failed")
