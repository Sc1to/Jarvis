"""
Web Push notification support.
VAPID keys are generated once at first startup and stored in trading_config.
Call init_vapid() in the lifespan before the first push is sent.
"""
import base64
import json
import logging
import sqlite3
from contextlib import contextmanager

from cryptography.hazmat.primitives.asymmetric.ec import generate_private_key, SECP256R1
from cryptography.hazmat.primitives.serialization import (
    Encoding, NoEncryption, PrivateFormat, PublicFormat,
)
from pywebpush import WebPushException, webpush

from db import DB_PATH

log = logging.getLogger(__name__)

_VAPID_CLAIMS = {"sub": "mailto:admin@platform.local"}


@contextmanager
def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _cfg(conn, key):
    row = conn.execute("SELECT value FROM trading_config WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def _set_cfg(conn, key, value):
    conn.execute(
        "INSERT OR REPLACE INTO trading_config (key, value, updated_at) VALUES (?, ?, datetime('now'))",
        (key, value),
    )


def init_vapid() -> None:
    """Generate VAPID keys if not present. Idempotent."""
    with _db() as conn:
        if _cfg(conn, "vapid_private_key"):
            return
        key = generate_private_key(SECP256R1())
        pub = base64.urlsafe_b64encode(
            key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
        ).rstrip(b"=").decode()
        priv = key.private_bytes(
            Encoding.PEM, PrivateFormat.TraditionalOpenSSL, NoEncryption()
        ).decode()
        _set_cfg(conn, "vapid_public_key", pub)
        _set_cfg(conn, "vapid_private_key", priv)
    log.info("VAPID keys generated")


def get_public_key() -> str:
    with _db() as conn:
        return _cfg(conn, "vapid_public_key") or ""


def save_subscription(endpoint: str, p256dh: str, auth: str) -> None:
    with _db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO trading_push_subscriptions (endpoint, p256dh, auth) VALUES (?, ?, ?)",
            (endpoint, p256dh, auth),
        )


def remove_subscription(endpoint: str) -> None:
    with _db() as conn:
        conn.execute(
            "DELETE FROM trading_push_subscriptions WHERE endpoint=?", (endpoint,)
        )


def send_push(title: str, body: str, url: str = "/trading/") -> None:
    """Blocking. Run via asyncio.to_thread from async contexts."""
    with _db() as conn:
        priv = _cfg(conn, "vapid_private_key")
        if not priv:
            return
        rows = conn.execute(
            "SELECT endpoint, p256dh, auth FROM trading_push_subscriptions"
        ).fetchall()

    if not rows:
        return

    payload = json.dumps({"title": title, "body": body, "url": url})
    dead: list[str] = []

    for row in rows:
        try:
            webpush(
                subscription_info={
                    "endpoint": row["endpoint"],
                    "keys": {"p256dh": row["p256dh"], "auth": row["auth"]},
                },
                data=payload,
                vapid_private_key=priv,
                vapid_claims=_VAPID_CLAIMS,
            )
        except WebPushException as exc:
            resp = getattr(exc, "response", None)
            if resp is not None and resp.status_code in (404, 410):
                dead.append(row["endpoint"])
            else:
                log.warning("Push failed: %s", exc)
        except Exception as exc:
            log.warning("Push error: %s", exc)

    if dead:
        with _db() as conn:
            for ep in dead:
                conn.execute(
                    "DELETE FROM trading_push_subscriptions WHERE endpoint=?", (ep,)
                )
        log.info("Removed %d dead push subscriptions", len(dead))
