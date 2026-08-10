import os
import sqlite3
import time
import uuid

DATA_ROOT = os.environ.get(
    "WRITER_DATA_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"),
)
DB_PATH = os.path.join(DATA_ROOT, "writer.db")

_conn: sqlite3.Connection | None = None


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        os.makedirs(DATA_ROOT, exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.executescript("""
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS books (
                id         TEXT PRIMARY KEY,
                title      TEXT NOT NULL,
                created_at INTEGER NOT NULL
            );
        """)
        _conn.commit()
    return _conn


def get_setting(key: str) -> str | None:
    row = _get_conn().execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_setting(key: str, value: str) -> None:
    _get_conn().execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    _get_conn().commit()


def get_all_settings() -> dict[str, str]:
    rows = _get_conn().execute("SELECT key, value FROM settings").fetchall()
    return {r["key"]: r["value"] for r in rows}


def list_books() -> list[dict]:
    rows = _get_conn().execute("SELECT * FROM books ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def create_book(title: str) -> dict:
    book_id = uuid.uuid4().hex[:8]
    created_at = int(time.time() * 1000)
    _get_conn().execute(
        "INSERT INTO books (id, title, created_at) VALUES (?, ?, ?)",
        (book_id, title, created_at),
    )
    _get_conn().commit()
    return {"id": book_id, "title": title, "created_at": created_at}


def get_book(book_id: str) -> dict | None:
    row = _get_conn().execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
    return dict(row) if row else None


def delete_book(book_id: str) -> None:
    _get_conn().execute("DELETE FROM books WHERE id = ?", (book_id,))
    _get_conn().commit()


def data_dir(book_id: str) -> str:
    return os.path.join(DATA_ROOT, book_id)


def ensure_data_dir(book_id: str) -> str:
    d = data_dir(book_id)
    os.makedirs(d, exist_ok=True)
    return d
