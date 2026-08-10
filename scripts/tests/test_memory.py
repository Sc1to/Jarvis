"""Memory infrastructure tests — session, project, and ChromaDB."""
import time
import uuid
import httpx

CONDUCTOR_PORT = 8001
DASHBOARD_PORT = 8050
CHROMA_PORT    = 8020


def _test_session_via_dashboard(base: str) -> tuple[bool, str]:
    """Create session, check it appears in dashboard API."""
    client = httpx.Client(base_url=f"{base}:{CONDUCTOR_PORT}", timeout=15)
    req_id = f"test-{uuid.uuid4().hex[:8]}"
    try:
        # Start a test session
        r = client.post("/session/start", json={
            "project_name": f"__test_{req_id}",
            "requirements": "Test session for memory validation. Do nothing.",
        })
        if r.status_code != 200:
            return False, f"session/start returned {r.status_code}: {r.text[:100]}"
        session_id = r.json().get("session_id")
        if not session_id:
            return False, "no session_id in response"

        # Verify it appears on the dashboard
        dash = httpx.get(f"{base}:{DASHBOARD_PORT}/sessions", timeout=10)
        ids = [s.get("id") for s in dash.json()]
        if session_id not in ids:
            return False, f"session {session_id} not found in dashboard"

        return True, f"session {session_id} created and visible in dashboard"
    except Exception as exc:
        return False, str(exc)
    finally:
        client.close()


def _test_chromadb(base: str) -> tuple[bool, str]:
    """Store and query a document in ChromaDB."""
    chroma = f"{base}:{CHROMA_PORT}"
    col_name = f"__test_{uuid.uuid4().hex[:8]}"
    try:
        # Create collection
        r = httpx.post(f"{chroma}/api/v1/collections", json={"name": col_name}, timeout=10)
        if r.status_code not in (200, 201):
            return False, f"create collection: HTTP {r.status_code}"
        col_id = r.json().get("id")

        # Add a document
        r = httpx.post(f"{chroma}/api/v1/collections/{col_id}/add", json={
            "ids": ["doc1"],
            "documents": ["The quick brown fox jumps over the lazy dog"],
            "metadatas": [{"source": "test"}],
        }, timeout=10)
        if r.status_code != 201:
            return False, f"add document: HTTP {r.status_code}"

        # Query it
        r = httpx.post(f"{chroma}/api/v1/collections/{col_id}/query", json={
            "query_texts": ["fox"],
            "n_results": 1,
        }, timeout=10)
        if r.status_code != 200:
            return False, f"query: HTTP {r.status_code}"
        ids = r.json().get("ids", [[]])
        if "doc1" not in ids[0]:
            return False, "query returned wrong document"

        # Clean up
        httpx.delete(f"{chroma}/api/v1/collections/{col_name}", timeout=10)
        return True, "store and semantic query successful"
    except Exception as exc:
        return False, str(exc)


def run(base_url: str) -> tuple[int, int]:
    passed = failed = 0

    for label, fn in [
        ("session creation + dashboard visibility", _test_session_via_dashboard),
        ("ChromaDB store and query",               _test_chromadb),
    ]:
        t0 = time.time()
        ok, detail = fn(base_url)
        ms = int((time.time() - t0) * 1000)
        status = "\033[32m[PASS]\033[0m" if ok else "\033[31m[FAIL]\033[0m"
        print(f"  {status}  {label}  ({ms}ms)")
        if not ok:
            print(f"         Detail: {detail}")
        passed += ok
        failed += (not ok)

    return passed, failed


if __name__ == "__main__":
    p, f = run("http://localhost")
    print(f"\n{p} passed, {f} failed")
