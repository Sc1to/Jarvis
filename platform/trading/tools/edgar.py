"""
SEC EDGAR REST API wrapper. No authentication required for public data.
EDGAR requires a User-Agent header identifying the accessing application.
"""
import logging

import httpx

log = logging.getLogger(__name__)

_DATA_BASE = "https://data.sec.gov"
_SEARCH_BASE = "https://efts.sec.gov/LATEST/search-index"
_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_HEADERS = {"User-Agent": "platform-trading admin@platform.local"}


class EdgarClient:
    """Async context manager for SEC EDGAR REST API."""

    def __init__(self):
        self._client = httpx.AsyncClient(timeout=20, headers=_HEADERS)
        self._ticker_cache: dict[str, str] = {}  # ticker → zero-padded CIK

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self._client.aclose()

    # ── Company lookup ────────────────────────────────────────────────────────

    async def get_cik(self, ticker: str) -> str | None:
        """Return 10-digit zero-padded CIK for a ticker, or None if not found."""
        t = ticker.upper()
        if t in self._ticker_cache:
            return self._ticker_cache[t]
        try:
            r = await self._client.get(_TICKERS_URL)
            r.raise_for_status()
            for entry in r.json().values():
                if entry.get("ticker", "").upper() == t:
                    cik = str(entry["cik_str"]).zfill(10)
                    self._ticker_cache[t] = cik
                    return cik
        except Exception as e:
            log.error("EDGAR CIK lookup failed for %s: %s", ticker, e)
        return None

    # ── Filings ───────────────────────────────────────────────────────────────

    async def get_filings(
        self, cik: str, form_type: str | None = None, limit: int = 10
    ) -> list[dict]:
        """
        Get recent filings for a company.
        cik must be 10-digit zero-padded.
        """
        try:
            r = await self._client.get(f"{_DATA_BASE}/submissions/CIK{cik}.json")
            r.raise_for_status()
        except Exception as e:
            log.error("EDGAR filings fetch failed for CIK %s: %s", cik, e)
            return []

        data = r.json()
        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accessions = recent.get("accessionNumber", [])
        docs = recent.get("primaryDocument", [])
        raw_cik = str(int(cik))  # strip leading zeros for URL

        results = []
        for form, date, acc, doc in zip(forms, dates, accessions, docs):
            if form_type and form != form_type:
                continue
            acc_clean = acc.replace("-", "")
            results.append({
                "form": form,
                "date": date,
                "accession": acc,
                "url": f"https://www.sec.gov/Archives/edgar/data/{raw_cik}/{acc_clean}/{doc}",
            })
            if len(results) >= limit:
                break
        return results

    async def get_latest_filing(self, ticker: str, form_type: str) -> dict | None:
        """Convenience: latest filing of a type for a ticker symbol."""
        cik = await self.get_cik(ticker)
        if not cik:
            return None
        filings = await self.get_filings(cik, form_type=form_type, limit=1)
        return filings[0] if filings else None

    async def search_filings(
        self, query: str, start_date: str = "2024-01-01", limit: int = 10
    ) -> list[dict]:
        """Full-text search across all public EDGAR filings."""
        try:
            r = await self._client.get(
                _SEARCH_BASE,
                params={"q": query, "dateRange": "custom", "startdt": start_date},
            )
            r.raise_for_status()
        except Exception as e:
            log.error("EDGAR search failed for '%s': %s", query, e)
            return []

        hits = r.json().get("hits", {}).get("hits", [])
        return [
            {
                "entity": h["_source"].get("entity_name"),
                "form": h["_source"].get("file_type"),
                "date": h["_source"].get("period_of_report"),
                "accession": h["_source"].get("file_date"),
            }
            for h in hits[:limit]
        ]
