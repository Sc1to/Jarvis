"""Frontend smoke tests using Playwright — visit each app, check key elements."""
import time

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

# app-name → (Caddy path, expected page title fragment, key selector)
APPS = [
    ("admin",     "/admin",     "Admin",     "text=Services"),
    ("chat",      "/chat",      "Chat",      "text=Send"),
    ("writer",    "/writer",    "Writer",    "textarea, [role=textbox]"),
    ("coding",    "/coding",    "Coding",    "text=Ask"),
    ("autocoder", "/autocoder", "Autocoder", "text=Project"),
]


def _check_app(page, base_url: str, path: str, title_fragment: str, selector: str) -> tuple[bool, str]:
    try:
        page.goto(f"{base_url}{path}", timeout=15000)
        page.wait_for_load_state("networkidle", timeout=10000)
        title = page.title()
        if title_fragment.lower() not in title.lower():
            return False, f"title {title!r} doesn't contain {title_fragment!r}"
        if not page.locator(selector).first.is_visible(timeout=5000):
            return False, f"selector {selector!r} not visible"
        return True, f"title={title!r}"
    except PwTimeout:
        return False, "timed out"
    except Exception as exc:
        return False, str(exc)


def run(base_url: str) -> tuple[int, int]:
    if not PLAYWRIGHT_AVAILABLE:
        print("  \033[33m[SKIP]\033[0m  Playwright not installed — run: pip install playwright && playwright install chromium")
        return 0, 0

    passed = failed = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()

        for name, path, title_frag, selector in APPS:
            t0 = time.time()
            ok, detail = _check_app(page, base_url, path, title_frag, selector)
            ms = int((time.time() - t0) * 1000)
            status = "\033[32m[PASS]\033[0m" if ok else "\033[31m[FAIL]\033[0m"
            print(f"  {status}  {name:<20} {detail}  ({ms}ms)")
            passed += ok
            failed += (not ok)

        browser.close()

    return passed, failed


if __name__ == "__main__":
    p, f = run("http://localhost")
    print(f"\n{p} passed, {f} failed")
