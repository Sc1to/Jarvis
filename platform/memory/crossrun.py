import logging
import os
from dataclasses import dataclass, field
from urllib.parse import urlparse
from uuid import uuid4

log = logging.getLogger(__name__)

_url = urlparse(os.environ.get("CHROMADB_URL", "http://localhost:8020"))
CHROMA_HOST = _url.hostname or "localhost"
CHROMA_PORT = _url.port or 8020

try:
    import chromadb as _chromadb
except ImportError:
    _chromadb = None  # type: ignore


@dataclass
class MemoryResult:
    content: str
    metadata: dict = field(default_factory=dict)
    distance: float = 0.0


class CrossRunMemory:
    def __init__(self, host: str = CHROMA_HOST, port: int = CHROMA_PORT):
        self._available = False
        if _chromadb is None:
            log.warning("chromadb not installed — cross-run memory disabled")
            return
        try:
            self._client = _chromadb.HttpClient(host=host, port=port)
            self._prefs = self._client.get_or_create_collection("preferences")
            self._resolutions = self._client.get_or_create_collection("resolutions")
            self._available = True
        except Exception as e:
            log.warning("ChromaDB unavailable at %s:%s — cross-run memory disabled: %s", host, port, e)

    @property
    def available(self) -> bool:
        return self._available

    # ── Write ─────────────────────────────────────────────────────────────────

    def store_preference(self, content: str, metadata: dict = {}) -> str:
        """Store a user preference or pattern. Returns the document ID."""
        if not self._available:
            return ""
        doc_id = str(uuid4())
        self._prefs.add(documents=[content], metadatas=[dict(metadata)], ids=[doc_id])
        return doc_id

    def store_resolution(
        self, failure_type: str, resolution: str, metadata: dict = {}
    ) -> str:
        """Store how a failure was resolved. Returns the document ID."""
        if not self._available:
            return ""
        doc_id = str(uuid4())
        meta = {**metadata, "failure_type": failure_type}
        self._resolutions.add(documents=[resolution], metadatas=[meta], ids=[doc_id])
        return doc_id

    # ── Read ──────────────────────────────────────────────────────────────────

    def query(self, text: str, n_results: int = 5) -> list[MemoryResult]:
        """Semantic search across both preferences and resolutions."""
        if not self._available:
            return []
        results = []
        for collection in (self._prefs, self._resolutions):
            try:
                r = collection.query(query_texts=[text], n_results=n_results)
                docs = r.get("documents", [[]])[0]
                metas = r.get("metadatas", [[]])[0]
                dists = r.get("distances", [[]])[0]
                for doc, meta, dist in zip(docs, metas, dists):
                    results.append(MemoryResult(content=doc, metadata=meta or {}, distance=dist))
            except Exception as e:
                log.warning("ChromaDB query error: %s", e)
        results.sort(key=lambda r: r.distance)
        return results[:n_results]

    def query_preferences(self, context: str, n_results: int = 3) -> list[MemoryResult]:
        """Semantic search over preferences collection only."""
        if not self._available:
            return []
        try:
            r = self._prefs.query(query_texts=[context], n_results=n_results)
            docs = r.get("documents", [[]])[0]
            metas = r.get("metadatas", [[]])[0]
            dists = r.get("distances", [[]])[0]
            return [
                MemoryResult(content=doc, metadata=meta or {}, distance=dist)
                for doc, meta, dist in zip(docs, metas, dists)
            ]
        except Exception as e:
            log.warning("ChromaDB query_preferences error: %s", e)
            return []

    def query_resolutions(
        self, failure_type: str, n_results: int = 3
    ) -> list[MemoryResult]:
        """Find past resolutions for a given failure type."""
        if not self._available:
            return []
        try:
            r = self._resolutions.query(
                query_texts=[failure_type],
                n_results=n_results,
                where={"failure_type": failure_type} if failure_type else None,
            )
            docs = r.get("documents", [[]])[0]
            metas = r.get("metadatas", [[]])[0]
            dists = r.get("distances", [[]])[0]
            return [
                MemoryResult(content=doc, metadata=meta or {}, distance=dist)
                for doc, meta, dist in zip(docs, metas, dists)
            ]
        except Exception as e:
            log.warning("ChromaDB query_resolutions error: %s", e)
            return []
