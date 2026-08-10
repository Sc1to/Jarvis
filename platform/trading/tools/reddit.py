"""
Reddit/praw wrapper for WSB monitoring.
Credentials in trading_config: reddit_client_id, reddit_client_secret, reddit_user_agent.
Read-only access — no posting, no voting, no authentication as user account.
"""
import logging
import re

import praw

log = logging.getLogger(__name__)

_TICKER_RE = re.compile(r'\b([A-Z]{2,5})\b')
_NOISE = {
    "I", "A", "THE", "AND", "OR", "IT", "US", "AT", "BE", "DO", "GO", "NO",
    "DD", "YOLO", "SEC", "CEO", "CFO", "CTO", "IPO", "ETF", "FD", "OTM",
    "ITM", "ATM", "EPS", "GDP", "WSB", "AMC", "FOR", "PUT", "CALL", "PE",
    "TV", "AI", "OP", "IS", "MY", "ON", "IN", "OF", "TO", "BY", "IF",
}


class RedditClient:
    def __init__(self, client_id: str, client_secret: str, user_agent: str):
        self._reddit = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            user_agent=user_agent,
        )
        self._wsb = self._reddit.subreddit("wallstreetbets")

    # ── Post fetching ─────────────────────────────────────────────────────────

    def get_dd_posts(self, limit: int = 25) -> list[dict]:
        """Get recent posts with DD flair from WSB."""
        posts = []
        for submission in self._wsb.new(limit=limit * 4):
            flair = submission.link_flair_text or ""
            if "DD" in flair.upper():
                posts.append(_serialize(submission))
                if len(posts) >= limit:
                    break
        return posts

    def get_hot_posts(self, limit: int = 50) -> list[dict]:
        return [_serialize(s) for s in self._wsb.hot(limit=limit)]

    def get_new_posts(self, limit: int = 100) -> list[dict]:
        return [_serialize(s) for s in self._wsb.new(limit=limit)]

    # ── Mention analysis ──────────────────────────────────────────────────────

    def count_ticker_mentions(
        self, tickers: list[str], posts: list[dict]
    ) -> dict[str, int]:
        """Count posts that contain each ticker symbol."""
        ticker_set = set(tickers)
        counts = {t: 0 for t in tickers}
        for post in posts:
            text = f"{post['title']} {post.get('selftext', '')}".upper()
            for t in _TICKER_RE.findall(text):
                if t in ticker_set:
                    counts[t] += 1
        return counts

    def extract_tickers(self, post: dict) -> list[str]:
        """Extract probable ticker symbols from a post, filtering noise words."""
        text = f"{post['title']} {post.get('selftext', '')}".upper()
        return sorted(set(_TICKER_RE.findall(text)) - _NOISE)


def _serialize(s) -> dict:
    return {
        "reddit_id": s.id,
        "title": s.title,
        "author": str(s.author) if s.author else "[deleted]",
        "flair": s.link_flair_text,
        "score": s.score,
        "url": s.url,
        "selftext": (s.selftext or "")[:2000],
        "created_utc": int(s.created_utc),
        "num_comments": s.num_comments,
    }
