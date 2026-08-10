#!/usr/bin/env python3
"""
Integration test for the autocoder pipeline.
Tests the Conductor + Dashboard backend without going through the RE-agent.

Usage:
    python scripts/test-autocoder-pipeline.py [--base-url http://localhost:8050]
"""

import argparse
import json
import sys
import time

import httpx

DASHBOARD = "http://localhost:8050"
CONDUCTOR = "http://localhost:8001"

REQUIREMENTS = """## Objective
Create a Python FastAPI endpoint GET /ping that returns {status: "ok", timestamp: ISO8601}.

## Scope
Included:
- Single FastAPI route GET /ping
- Returns JSON with status and timestamp fields
- Unit test for the endpoint

Excluded:
- Authentication
- Database
- Any other endpoints

## Constraints
- Python 3.12
- FastAPI 0.115.x
- Response must be valid JSON

## Acceptance Criteria
- GET /ping returns HTTP 200
- Response body contains status field with value "ok"
- Response body contains timestamp field in ISO 8601 format
- Unit test passes

## Tech Context
Standalone FastAPI service. No existing codebase to integrate with.
Create main.py and test_main.py in the project directory.
"""


def check(label: str, ok: bool, detail: str = ""):
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] {label}" + (f" — {detail}" if detail else ""))
    return ok


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dashboard", default=DASHBOARD)
    parser.add_argument("--conductor", default=CONDUCTOR)
    args = parser.parse_args()

    dashboard = args.dashboard
    conductor = args.conductor

    results = []
    print("\n=== Autocoder Pipeline Integration Test ===\n")

    # 1. Health checks
    print("1. Service health")
    with httpx.Client(timeout=5.0) as client:
        for name, url in [("Dashboard", dashboard), ("Conductor", conductor)]:
            try:
                r = client.get(f"{url}/health")
                ok = r.status_code == 200 and r.json().get("status") == "ok"
                results.append(check(f"{name} health", ok, r.json().get("status", "?")))
            except Exception as e:
                results.append(check(f"{name} health", False, str(e)))

    # 2. Specialist health checks (best-effort — may not be running yet)
    print("\n2. Specialist agent health (informational)")
    specialists = {
        "Backend":    "http://localhost:8003",
        "Frontend":   "http://localhost:8004",
        "DB":         "http://localhost:8005",
        "Tester":     "http://localhost:8006",
        "Refactorer": "http://localhost:8007",
        "RE-agent":   "http://localhost:8002",
    }
    with httpx.Client(timeout=3.0) as client:
        for name, url in specialists.items():
            try:
                r = client.get(f"{url}/health")
                check(f"{name} reachable", r.status_code == 200)
            except Exception:
                check(f"{name} reachable", False, "not running")

    # 3. Create a test project in memory
    print("\n3. Project and session setup")
    project_id = None
    with httpx.Client(timeout=10.0) as client:
        try:
            # Check if projects endpoint works
            r = client.get(f"{dashboard}/projects")
            results.append(check("GET /projects", r.status_code == 200))
        except Exception as e:
            results.append(check("GET /projects", False, str(e)))

    # 4. Start a session via Conductor
    print("\n4. Start autocoder session")
    session_id = None
    with httpx.Client(timeout=15.0) as client:
        try:
            r = client.post(f"{conductor}/session/start", json={
                "project_id": None,
                "requirements_document": REQUIREMENTS,
            })
            ok = r.status_code == 200
            if ok:
                session_id = r.json().get("data", {}).get("session_id")
            results.append(check("POST /session/start", ok and bool(session_id), f"session_id={session_id}"))
        except Exception as e:
            results.append(check("POST /session/start", False, str(e)))

    if not session_id:
        print("\nCannot continue without session_id.")
        _summary(results)
        return

    # 5. Verify session appears in dashboard
    print("\n5. Session visible in dashboard")
    time.sleep(1)
    with httpx.Client(timeout=10.0) as client:
        try:
            r = client.get(f"{dashboard}/sessions/{session_id}")
            ok = r.status_code == 200
            status = r.json().get("data", {}).get("status") if ok else "?"
            results.append(check("GET /sessions/{id}", ok, f"status={status}"))
        except Exception as e:
            results.append(check("GET /sessions/{id}", False, str(e)))

    # 6. Poll for pipeline events (max 30s — pipeline may park quickly if no specialists)
    print("\n6. Pipeline event logging (polling 30s)")
    deadline = time.time() + 30
    got_events = False
    final_status = None
    with httpx.Client(timeout=10.0) as client:
        while time.time() < deadline:
            time.sleep(3)
            try:
                r = client.get(f"{dashboard}/sessions/{session_id}/log")
                events = r.json().get("data", [])
                if events:
                    got_events = True
                r2 = client.get(f"{dashboard}/sessions/{session_id}")
                sess = r2.json().get("data", {})
                final_status = sess.get("status")
                if final_status in ("closed",):
                    break
            except Exception:
                pass

    results.append(check("Events logged to session", got_events,
                          f"{len(events)} events" if got_events else "no events"))

    # 7. Check agent status endpoint
    print("\n7. Agent status")
    with httpx.Client(timeout=10.0) as client:
        try:
            r = client.get(f"{dashboard}/agents/status")
            ok = r.status_code == 200
            agents = r.json().get("data", [])
            conductor_info = next((a for a in agents if a["agent_name"] == "conductor"), None)
            results.append(check("GET /agents/status", ok, f"{len(agents)} agents listed"))
            if conductor_info:
                check("Conductor status tracked", True, f"status={conductor_info['status']}")
        except Exception as e:
            results.append(check("GET /agents/status", False, str(e)))

    # 8. Session pause/resume
    print("\n8. Pause/resume endpoints")
    with httpx.Client(timeout=10.0) as client:
        for action in ("pause", "resume"):
            try:
                r = client.post(f"{conductor}/session/{session_id}/{action}")
                results.append(check(f"POST /session/{{id}}/{action}", r.status_code == 200))
            except Exception as e:
                results.append(check(f"POST /session/{{id}}/{action}", False, str(e)))

    # 9. Print session log summary
    print("\n9. Session log summary")
    with httpx.Client(timeout=10.0) as client:
        try:
            r = client.get(f"{dashboard}/sessions/{session_id}/log")
            events = r.json().get("data", [])
            print(f"   Total events: {len(events)}")
            for e in events[:10]:
                ts = e.get("timestamp", "")[-8:] if e.get("timestamp") else ""
                print(f"   {ts}  [{e.get('agent', '?')!s:<12}] {e.get('event_type', '?')!s:<15} {e.get('content', '')[:60]}")
        except Exception as e:
            print(f"   Could not fetch log: {e}")

    _summary(results)


def _summary(results: list[bool]):
    passed = sum(results)
    total = len(results)
    print(f"\n{'='*44}")
    print(f"Result: {passed}/{total} checks passed")
    if passed == total:
        print("All checks passed ✓")
    else:
        print(f"{total - passed} check(s) failed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
