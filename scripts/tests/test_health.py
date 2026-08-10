"""Health check tests — every registered service must return {status: ok}."""
import time
import httpx

SERVICES = [
    ("admin",                        8000),
    ("chat",                         8010),
    ("writer",                       8011),
    ("coding",                       8012),
    ("autocoder-conductor",          8001),
    ("autocoder-re-agent",           8002),
    ("autocoder-dashboard",          8050),
    ("autocoder-specialist-backend", 8003),
    ("autocoder-specialist-frontend",8004),
    ("autocoder-specialist-db",      8005),
    ("autocoder-specialist-tester",  8006),
    ("autocoder-specialist-refactorer", 8007),
    ("trading",                      8030),
    ("trading-auditor",              8031),
]


def _check(name: str, url: str) -> tuple[bool, str]:
    try:
        r = httpx.get(url, timeout=5)
        body = r.json()
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}"
        if body.get("status") not in ("ok", "degraded"):
            return False, f"unexpected status: {body.get('status')!r}"
        uptime = body.get("uptime_seconds", -1)
        if uptime < 0:
            return False, "uptime_seconds missing or negative"
        return True, f"up {uptime}s"
    except Exception as exc:
        return False, str(exc)


def run(base_url: str) -> tuple[int, int]:
    passed = failed = 0
    for name, port in SERVICES:
        url = f"{base_url}:{port}/health"
        t0 = time.time()
        ok, detail = _check(name, url)
        ms = int((time.time() - t0) * 1000)
        status = "\033[32m[PASS]\033[0m" if ok else "\033[31m[FAIL]\033[0m"
        print(f"  {status}  {name:<40} {detail}  ({ms}ms)")
        if ok:
            passed += 1
        else:
            failed += 1
    return passed, failed


if __name__ == "__main__":
    p, f = run("http://localhost")
    print(f"\n{p} passed, {f} failed")
