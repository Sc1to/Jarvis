"""Ollama model tests — check models are downloaded and respond."""
import time
import httpx

REQUIRED_MODELS = [
    "qwen2.5:14b",
    "qwen2.5-coder:32b",
    "qwen2.5:72b-instruct-q4_K_M",
]
TEST_PROMPT = "Reply with exactly the word: HELLO"


def _list_models(ollama_url: str) -> list[str]:
    r = httpx.get(f"{ollama_url}/api/tags", timeout=10)
    r.raise_for_status()
    return [m["name"] for m in r.json().get("models", [])]


def _chat(ollama_url: str, model: str) -> tuple[bool, float, str]:
    t0 = time.time()
    try:
        r = httpx.post(
            f"{ollama_url}/api/chat",
            json={"model": model, "messages": [{"role": "user", "content": TEST_PROMPT}], "stream": False},
            timeout=120,
        )
        r.raise_for_status()
        content = r.json().get("message", {}).get("content", "")
        latency = time.time() - t0
        return bool(content), latency, content[:80]
    except Exception as exc:
        return False, time.time() - t0, str(exc)


def run(base_url: str) -> tuple[int, int]:
    ollama_url = f"{base_url}:11434"
    passed = failed = 0

    # Check models are present
    try:
        available = _list_models(ollama_url)
    except Exception as exc:
        print(f"  \033[31m[FAIL]\033[0m  Cannot reach Ollama at {ollama_url}: {exc}")
        return 0, len(REQUIRED_MODELS) * 2

    for model in REQUIRED_MODELS:
        present = any(m == model or m.startswith(model.split(":")[0]) for m in available)
        if present:
            print(f"  \033[32m[PASS]\033[0m  {model} — downloaded")
            passed += 1
        else:
            print(f"  \033[31m[FAIL]\033[0m  {model} — NOT downloaded")
            failed += 1
            continue

        # Send test prompt
        ok, latency, reply = _chat(ollama_url, model)
        if ok:
            print(f"  \033[32m[PASS]\033[0m  {model} — responded in {latency:.1f}s: {reply!r}")
            passed += 1
        else:
            print(f"  \033[31m[FAIL]\033[0m  {model} — no response: {reply}")
            failed += 1

    return passed, failed


if __name__ == "__main__":
    p, f = run("http://localhost")
    print(f"\n{p} passed, {f} failed")
