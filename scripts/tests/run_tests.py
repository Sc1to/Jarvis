#!/usr/bin/env python3
"""
Test runner for the Jarvis platform.

Usage:
  python run_tests.py --target local
  python run_tests.py --target remote
  python run_tests.py --target local --suite health,models
  python run_tests.py --target remote --suite all
"""
import argparse
import importlib
import sys
import time

# Base URLs for each target
TARGETS = {
    "local":  "http://localhost",
    "remote": "http://ms-s1",   # accessible via Tailscale
}

SUITES = ["health", "models", "memory", "tools", "pipeline", "ui"]


def run_suite(name: str, base_url: str) -> tuple[int, int]:
    """Import and run a test module. Returns (passed, failed)."""
    mod = importlib.import_module(f"test_{name}")
    return mod.run(base_url)


def main():
    parser = argparse.ArgumentParser(description="Platform test runner")
    parser.add_argument("--target", choices=["local", "remote"], default="local")
    parser.add_argument("--suite", default="all",
                        help="Comma-separated list of suites, or 'all'")
    args = parser.parse_args()

    base_url = TARGETS[args.target]
    suites = SUITES if args.suite == "all" else [s.strip() for s in args.suite.split(",")]

    # Validate suite names
    unknown = [s for s in suites if s not in SUITES]
    if unknown:
        print(f"Unknown suites: {unknown}. Valid: {SUITES}")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  Target: {args.target}  ({base_url})")
    print(f"  Suites: {', '.join(suites)}")
    print(f"{'='*60}\n")

    total_passed = total_failed = 0
    results = []
    t0 = time.time()

    for suite in suites:
        print(f"\n── {suite.upper()} ──")
        try:
            passed, failed = run_suite(suite, base_url)
        except Exception as exc:
            print(f"  [ERROR] Suite {suite} crashed: {exc}")
            passed, failed = 0, 1
        total_passed += passed
        total_failed += failed
        results.append((suite, passed, failed))

    elapsed = time.time() - t0
    print(f"\n{'='*60}")
    print(f"  Results: {total_passed} passed, {total_failed} failed  ({elapsed:.1f}s)")
    for suite, p, f in results:
        status = "\033[32mPASS\033[0m" if f == 0 else "\033[31mFAIL\033[0m"
        print(f"    {status}  {suite}  ({p}p/{f}f)")
    print(f"{'='*60}\n")

    sys.exit(0 if total_failed == 0 else 1)


if __name__ == "__main__":
    main()
