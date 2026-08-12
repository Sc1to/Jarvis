"""Kill the admin uvicorn process so systemd restarts it with new code.
Called as a postbuild npm lifecycle hook — runs after successful vite build.
No sudo needed: jarvis owns the uvicorn process."""
import os
import signal

for p in os.listdir("/proc"):
    if not p.isdigit():
        continue
    try:
        cmd = open("/proc/" + p + "/cmdline", "rb").read().replace(b"\x00", b" ").decode("latin1")
        if "uvicorn" in cmd and "main:app" in cmd:
            os.kill(int(p), signal.SIGTERM)
    except Exception:
        pass
