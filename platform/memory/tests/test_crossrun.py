from unittest.mock import MagicMock, patch

import pytest

from memory.crossrun import CrossRunMemory, MemoryResult


def _mock_collection(docs=None, metas=None, dists=None):
    """Build a mock ChromaDB collection with preset query results."""
    col = MagicMock()
    col.query.return_value = {
        "documents": [docs or []],
        "metadatas": [metas or []],
        "distances": [dists or []],
    }
    return col


def _make_mem(prefs_col=None, resolutions_col=None):
    """Return a CrossRunMemory wired to mock collections."""
    with patch("memory.crossrun._chromadb") as mock_chroma:
        mock_client = MagicMock()
        mock_chroma.HttpClient.return_value = mock_client
        mock_client.get_or_create_collection.side_effect = [
            prefs_col or MagicMock(),
            resolutions_col or MagicMock(),
        ]
        return CrossRunMemory()


def test_available_when_chromadb_present():
    mem = _make_mem()
    assert mem.available is True


def test_unavailable_when_chromadb_missing():
    with patch("memory.crossrun._chromadb", None):
        mem = CrossRunMemory()
    assert mem.available is False


def test_unavailable_when_chroma_unreachable():
    with patch("memory.crossrun._chromadb") as mock_chroma:
        mock_chroma.HttpClient.side_effect = ConnectionRefusedError("refused")
        mem = CrossRunMemory()
    assert mem.available is False


def test_store_preference_returns_id():
    prefs = MagicMock()
    mem = _make_mem(prefs_col=prefs)
    doc_id = mem.store_preference("Prefer minimal comments", {"project": "global"})
    assert len(doc_id) == 36  # UUID
    prefs.add.assert_called_once()


def test_store_preference_unavailable_returns_empty():
    with patch("memory.crossrun._chromadb", None):
        mem = CrossRunMemory()
    assert mem.store_preference("something") == ""


def test_store_resolution_returns_id():
    resolutions = MagicMock()
    mem = _make_mem(resolutions_col=resolutions)
    doc_id = mem.store_resolution("solvable", "Retry with refined instructions")
    assert len(doc_id) == 36
    resolutions.add.assert_called_once()
    _, kwargs = resolutions.add.call_args
    assert kwargs["metadatas"][0]["failure_type"] == "solvable"


def test_query_returns_results():
    prefs = _mock_collection(
        docs=["prefer snake_case", "no comments unless necessary"],
        metas=[{"source": "pref"}, {"source": "pref"}],
        dists=[0.1, 0.3],
    )
    resolutions = _mock_collection()
    mem = _make_mem(prefs_col=prefs, resolutions_col=resolutions)
    results = mem.query("coding style preferences", n_results=5)
    assert len(results) == 2
    assert results[0].content == "prefer snake_case"
    assert results[0].distance == 0.1


def test_query_sorted_by_distance():
    prefs = _mock_collection(docs=["a", "b"], metas=[{}, {}], dists=[0.5, 0.2])
    resolutions = _mock_collection()
    mem = _make_mem(prefs_col=prefs, resolutions_col=resolutions)
    results = mem.query("something")
    assert results[0].distance < results[1].distance


def test_query_empty_when_unavailable():
    with patch("memory.crossrun._chromadb", None):
        mem = CrossRunMemory()
    assert mem.query("anything") == []


def test_query_preferences_only():
    prefs = _mock_collection(docs=["user prefers minimal code"], metas=[{}], dists=[0.1])
    resolutions = MagicMock()  # should NOT be called
    mem = _make_mem(prefs_col=prefs, resolutions_col=resolutions)
    results = mem.query_preferences("code style")
    assert len(results) == 1
    resolutions.query.assert_not_called()


def test_query_resolutions():
    resolutions = _mock_collection(
        docs=["swap to larger model"], metas=[{"failure_type": "capability"}], dists=[0.05]
    )
    mem = _make_mem(resolutions_col=resolutions)
    results = mem.query_resolutions("capability")
    assert len(results) == 1
    assert results[0].metadata["failure_type"] == "capability"


def test_memory_result_defaults():
    r = MemoryResult(content="test")
    assert r.metadata == {}
    assert r.distance == 0.0
