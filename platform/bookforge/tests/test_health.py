"""Health check and envelope tests for the bookforge service shell (milestone 14.0)."""

import os
import sys

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import main  # noqa: E402

client = TestClient(main.app, raise_server_exceptions=False)


def test_health_shape():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["version"] == main.VERSION
    assert isinstance(body["uptime_seconds"], int) and body["uptime_seconds"] >= 0


def test_status_uses_success_envelope():
    r = client.get("/api/status")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["data"]["service"] == "platform-bookforge"
    assert body["data"]["milestone"] == "14.0"


def test_data_dir_follows_env(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "DATA_DIR", str(tmp_path))
    data = client.get("/api/status").json()["data"]
    assert data["data_dir"] == str(tmp_path)
    assert data["data_dir_exists"] is True


def test_unknown_route_uses_error_envelope():
    r = client.get("/api/does-not-exist")
    assert r.status_code == 404
    body = r.json()
    assert body["status"] == "error"
    assert body["error"] == "http_error"
    assert "detail" in body


def test_unhandled_exception_uses_error_envelope(monkeypatch):
    def boom():
        raise RuntimeError("boom")

    monkeypatch.setattr(main.os.path, "isdir", lambda _p: boom())
    r = client.get("/api/status")
    assert r.status_code == 500
    body = r.json()
    assert body["status"] == "error"
    assert "boom" in body["detail"]
