import json
from fastapi.testclient import TestClient
from backend.main import app
from backend import live_knowledge as live


def test_public_browsers_cannot_read_or_overwrite_each_other(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", str(tmp_path / "users.db"))
    monkeypatch.setenv("DEPLOYMENT_MODE", "public")
    with TestClient(app, base_url="https://testserver") as first, TestClient(app, base_url="https://testserver") as second:
        first.get("/healthz")
        second.get("/healthz")
        assert first.cookies.get("gg_session") != second.cookies.get("gg_session")
        assert first.post("/api/consent", json={"village":"A", "state":"Uttar Pradesh", "district":"Jaunpur", "consent":True}).status_code == 200
        assert second.get("/api/profile", headers={"X-User-Id":"1"}).status_code in (403,404)
        assert second.post("/api/consent", json={"village":"B", "state":"Maharashtra", "district":"Pune", "consent":True}).status_code == 200
        assert first.get("/api/profile").json()["household"]["village"] == "A"
        assert second.get("/api/profile").json()["household"]["village"] == "B"
        assert "no-store" in first.get("/api/profile").headers["cache-control"]


def test_location_cache_isolation_and_failed_refresh_retains_timestamp(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    a={"state":"Uttar Pradesh","district":"Jaunpur","village":"Newada","block":"Sirkoni"}
    b={"state":"Maharashtra","district":"Pune","village":"Example"}
    assert live.key_for(a) != live.key_for(b)
    assert live.key_for(a) != live.key_for({**a,"block":"Other"})
    monkeypatch.setattr(live,"collect",lambda region:{"schemes":[],"projects":[{"title":region["district"]}],"errors":[]})
    initial=live.refresh(a)
    live.refresh(b)
    def broken(region): raise ValueError("Source unavailable")
    monkeypatch.setattr(live,"collect",broken)
    stale=live.refresh(a)
    assert stale["status"] == "stale"
    assert stale["checkedAt"] == initial["checkedAt"]
    assert stale["projects"][0]["title"] == "Jaunpur"
    assert json.loads(live.cache_path(b).read_text())["projects"][0]["title"] == "Pune"


def test_only_official_https_sources():
    assert live.official("https://jaunpur.nic.in/schemes/")
    assert not live.official("https://jaunpur.nic.in.evil.example/")
    assert not live.official("http://127.0.0.1/")
    assert not live.official("https://example.gov.in:9999/")
