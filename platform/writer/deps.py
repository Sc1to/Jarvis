from fastapi import Header


def current_user(tailscale_user_login: str | None = Header(default=None, alias="Tailscale-User-Login")) -> str:
    # Falls back to "local" for direct/dev access not going through Tailscale Serve
    return tailscale_user_login or "local"
