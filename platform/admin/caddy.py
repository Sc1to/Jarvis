import os
import re
import subprocess

CADDYFILE = os.environ.get("CADDYFILE_PATH", "/etc/caddy/Caddyfile")


def _read() -> str:
    with open(CADDYFILE) as f:
        return f.read()


def _write(content: str):
    # Write via sudo tee so the ubuntu user doesn't need write permission on /etc/caddy
    proc = subprocess.run(["sudo", "tee", CADDYFILE], input=content, text=True, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"Failed to write Caddyfile: {proc.stderr}")
    # Normalize formatting so caddy validate never warns about inconsistencies
    fmt = subprocess.run(["sudo", "caddy", "fmt", "--overwrite", CADDYFILE], capture_output=True, text=True)
    if fmt.returncode != 0:
        raise RuntimeError(f"caddy fmt failed: {fmt.stderr}")


def _reload():
    subprocess.run(["sudo", "systemctl", "reload", "caddy"], check=True, timeout=10)


def add_route(route: str, backend_port: int):
    content = _read()
    block = (
        f'    handle {route}* {{\n'
        f'        uri strip_prefix {route}\n'
        f'        reverse_proxy localhost:{backend_port}\n'
        f'    }}\n'
    )
    idx = content.rfind('}')
    content = content[:idx] + block + content[idx:]
    _write(content)
    _reload()


def remove_route(route: str):
    content = _read()
    escaped = re.escape(route)
    content = re.sub(rf'\n\s*handle {escaped}\*\s*\{{[^}}]*\}}', '', content)
    _write(content)
    _reload()
