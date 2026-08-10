import time


def health_payload(start_time: float, version: str, **extra) -> dict:
    payload = {"status": "ok", "version": version, "uptime_seconds": int(time.time() - start_time)}
    payload.update(extra)
    return payload
