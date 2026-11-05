"""Web Push for the dashboard: a notification when a run needs you or fails.

Same scheme as the trading app (VAPID keys, one subscription per browser), but kept in its own SQLite file,
`<data dir>/push.db`, outside the series folders so the keys never end up in a series' Git history. The
private key is generated on first use. `pywebpush` is imported only when a push is actually sent.
"""

import base64
import json
import logging
import sqlite3
import threading
from contextlib import closing
from pathlib import Path
from typing import Callable

log = logging.getLogger("platform_bookforge.push")

VAPID_CLAIMS = {"sub": "mailto:admin@platform.local"}
_lock = threading.Lock()


def _connect(db: Path) -> sqlite3.Connection:
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS subscriptions (endpoint TEXT PRIMARY KEY, p256dh TEXT NOT NULL, auth TEXT NOT NULL)")
    return conn


def _generate_keys() -> tuple[str, str]:
    from cryptography.hazmat.primitives.asymmetric.ec import SECP256R1, generate_private_key
    from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

    key = generate_private_key(SECP256R1())
    public = base64.urlsafe_b64encode(key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)).rstrip(b"=").decode()
    private = key.private_bytes(Encoding.PEM, PrivateFormat.TraditionalOpenSSL, NoEncryption()).decode()
    return public, private


def _keys(conn: sqlite3.Connection) -> tuple[str, str]:
    rows = dict(conn.execute("SELECT key, value FROM config WHERE key IN ('vapid_public_key', 'vapid_private_key')").fetchall())
    if "vapid_private_key" not in rows:
        public, private = _generate_keys()
        with conn:
            conn.executemany("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
                             [("vapid_public_key", public), ("vapid_private_key", private)])
        log.info("VAPID keys generated")
        return public, private
    return rows["vapid_public_key"], rows["vapid_private_key"]


def public_key(db: Path) -> str:
    with _lock, closing(_connect(db)) as conn:
        return _keys(conn)[0]


def subscribe(db: Path, endpoint: str, p256dh: str, auth: str) -> None:
    with _lock, closing(_connect(db)) as conn, conn:
        conn.execute("INSERT OR REPLACE INTO subscriptions (endpoint, p256dh, auth) VALUES (?, ?, ?)", (endpoint, p256dh, auth))


def unsubscribe(db: Path, endpoint: str) -> None:
    with _lock, closing(_connect(db)) as conn, conn:
        conn.execute("DELETE FROM subscriptions WHERE endpoint=?", (endpoint,))


def subscription_count(db: Path) -> int:
    with _lock, closing(_connect(db)) as conn:
        return conn.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0]


def _webpush(**kwargs):
    from pywebpush import webpush

    return webpush(**kwargs)


def send(db: Path, title: str, body: str, url: str, sender: Callable | None = None) -> int:
    """Send to every subscription; returns how many were delivered. Dead subscriptions (404/410) are removed.
    Never raises: a notification problem must not fail a run."""
    try:
        with _lock, closing(_connect(db)) as conn:
            _, private = _keys(conn)
            rows = conn.execute("SELECT endpoint, p256dh, auth FROM subscriptions").fetchall()
    except Exception as e:
        log.warning("push: cannot read %s: %s", db, e)
        return 0
    payload = json.dumps({"title": title, "body": body, "url": url})
    send_one = sender or _webpush
    delivered, dead = 0, []
    for row in rows:
        try:
            send_one(subscription_info={"endpoint": row["endpoint"], "keys": {"p256dh": row["p256dh"], "auth": row["auth"]}},
                     data=payload, vapid_private_key=private, vapid_claims=dict(VAPID_CLAIMS))
            delivered += 1
        except Exception as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status in (404, 410):
                dead.append(row["endpoint"])
            else:
                log.warning("push failed: %s", e)
    for endpoint in dead:
        unsubscribe(db, endpoint)
    return delivered
