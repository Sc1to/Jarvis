"""
trading_wsb_dd — 13.8
Monitors r/wallstreetbets for DD-flair posts, uses qwen2.5:14b to extract
thesis quality + ticker, cross-references with SEC EDGAR, emits DD signals.
"""
import json
import logging
import re
import sqlite3

import httpx

from db import DB_PATH, OLLAMA_BASE
from tools.reddit import RedditClient
from tools.edgar import EdgarClient

log = logging.getLogger(__name__)

OLLAMA_URL = f"{OLLAMA_BASE}/api/generate"
OLLAMA_MODEL = "qwen2.5:14b"
QUALITY_THRESHOLD = 40     # minimum to emit a signal
EDGAR_LOOKBACK_DAYS = 30   # look for SEC filings within this window

_EXTRACTION_PROMPT = """\
You are a financial analyst reviewing a post from r/wallstreetbets.
Extract structured information from the post below.

Title: {title}

Post body:
{body}

Return ONLY a valid JSON object with these exact keys:
{{
  "ticker": "<PRIMARY TICKER (2-5 uppercase letters) or null if ambiguous>",
  "thesis_summary": "<1-2 sentence summary of the investment case>",
  "timeframe": "<'short' (days-weeks) | 'medium' (1-3 months) | 'long' (3+ months) | null>",
  "catalyst": "<specific near-term event driving the thesis, or null>",
  "quality_score": <integer 0-100 based on this rubric:
    +20 if a specific ticker is clearly identified
    +20 if the thesis is coherent and explains WHY the stock moves
    +25 if concrete data or numbers are cited (earnings, revenue, margins, price targets)
    +20 if a specific upcoming catalyst is named (earnings date, FDA decision, product launch)
    +15 if a realistic timeframe is mentioned
    Deduct points for: meme stocks with no thesis, pure momentum play, options spam, YOLO posts>
}}"""


async def run():
    """Entry point called by scheduler every 30 minutes."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        client_id = _cfg(conn, "reddit_client_id")
        client_secret = _cfg(conn, "reddit_client_secret")
        user_agent = _cfg(conn, "reddit_user_agent") or "platform-trading/1.0"
    finally:
        conn.close()

    if not client_id or not client_secret:
        log.warning("Reddit credentials not configured — wsb_dd skipped")
        return

    reddit = RedditClient(client_id, client_secret, user_agent)

    try:
        posts = reddit.get_dd_posts(limit=25)
    except Exception as e:
        log.error("Reddit fetch failed: %s", e)
        return

    new_posts = _filter_unprocessed(posts)
    if not new_posts:
        log.debug("No new DD posts this cycle")
        return

    log.info("Processing %d new DD posts", len(new_posts))

    async with EdgarClient() as edgar:
        for post in new_posts:
            try:
                await _process_post(post, edgar)
            except Exception as e:
                log.error("Error processing post %s: %s", post.get("reddit_id"), e)


async def _process_post(post: dict, edgar: EdgarClient):
    # LLM extraction
    extracted = await _extract_thesis(post)
    if not extracted:
        _mark_processed(post, extracted={}, quality_score=0, catalyst_verified=False)
        return

    ticker = extracted.get("ticker")
    quality = int(extracted.get("quality_score") or 0)
    catalyst = extracted.get("catalyst")

    # EDGAR cross-reference
    catalyst_verified = False
    if ticker and catalyst:
        catalyst_verified = await _verify_with_edgar(edgar, ticker)

    _mark_processed(post, extracted, quality, catalyst_verified)

    if ticker and quality >= QUALITY_THRESHOLD:
        _emit_signal(
            ticker=ticker,
            thesis=extracted.get("thesis_summary", ""),
            quality_score=quality,
            catalyst_verified=catalyst_verified,
            source_url=post.get("url", ""),
        )
        log.info("DD signal: %s quality=%d edgar=%s", ticker, quality, catalyst_verified)


async def _extract_thesis(post: dict) -> dict | None:
    prompt = _EXTRACTION_PROMPT.format(
        title=post.get("title", ""),
        body=(post.get("selftext") or "")[:2000],
    )
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                OLLAMA_URL,
                json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False, "format": "json"},
            )
            r.raise_for_status()
            text = r.json().get("response", "")
        return _parse_json(text)
    except Exception as e:
        log.error("LLM extraction failed: %s", e)
        return None


async def _verify_with_edgar(edgar: EdgarClient, ticker: str) -> bool:
    """Return True if ticker has had recent SEC filings (8-K or 10-Q) in last N days."""
    try:
        cik = await edgar.get_cik(ticker)
        if not cik:
            return False
        filings = await edgar.get_filings(cik, limit=5)
        from datetime import date, timedelta
        cutoff = (date.today() - timedelta(days=EDGAR_LOOKBACK_DAYS)).isoformat()
        return any(f["date"] >= cutoff for f in filings if f.get("form") in ("8-K", "10-Q", "10-K"))
    except Exception as e:
        log.debug("EDGAR check failed for %s: %s", ticker, e)
        return False


def _filter_unprocessed(posts: list[dict]) -> list[dict]:
    if not posts:
        return []
    ids = tuple(p["reddit_id"] for p in posts)
    placeholders = ",".join("?" * len(ids))
    conn = sqlite3.connect(DB_PATH)
    try:
        existing = {
            r[0]
            for r in conn.execute(
                f"SELECT reddit_id FROM trading_wsb_posts WHERE reddit_id IN ({placeholders})", ids
            ).fetchall()
        }
    finally:
        conn.close()
    return [p for p in posts if p["reddit_id"] not in existing]


def _mark_processed(post: dict, extracted: dict, quality_score: int, catalyst_verified: bool):
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            """INSERT OR IGNORE INTO trading_wsb_posts
               (reddit_id, title, author, flair, score, ticker,
                thesis_summary, quality_score, catalyst_verified, source_url, created_utc)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                post.get("reddit_id"),
                post.get("title"),
                post.get("author"),
                post.get("flair"),
                post.get("score", 0),
                extracted.get("ticker") if extracted else None,
                extracted.get("thesis_summary") if extracted else None,
                quality_score,
                1 if catalyst_verified else 0,
                post.get("url"),
                post.get("created_utc"),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _emit_signal(ticker: str, thesis: str, quality_score: int, catalyst_verified: bool, source_url: str):
    meta = {
        "thesis_summary": thesis,
        "quality_score": quality_score,
        "catalyst_verified": catalyst_verified,
        "source_url": source_url,
    }
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            """INSERT INTO trading_signals
               (pool, ticker, signal_type, direction, strength, metadata)
               VALUES (
                 CASE WHEN ? LIKE '%-USD' THEN 'crypto' ELSE 'stocks' END,
                 ?, 'wsb_dd', 'BUY', ?, ?)""",
            (ticker, ticker, float(quality_score), json.dumps(meta)),
        )
        conn.commit()
    finally:
        conn.close()


def _parse_json(text: str) -> dict | None:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    return None


def _cfg(conn, key: str) -> str:
    row = conn.execute("SELECT value FROM trading_config WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else ""
