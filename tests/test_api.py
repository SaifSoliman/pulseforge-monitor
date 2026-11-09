from app.config import Settings
from app.main import create_app
from fastapi.testclient import TestClient


def test_health_and_empty_dashboard(client):
    assert client.get("/healthz").json()["status"] == "ok"
    assert client.get("/readyz").status_code == 200
    assert client.get("/").status_code == 200
    data = client.get("/api/overview").json()
    assert data["total"] == 0
    assert data["uptime_24h"] is None


def test_monitor_create_edit_remove(client, monitor_payload):
    resp = client.post("/api/monitors", json=monitor_payload)
    assert resp.status_code == 201
    monitor = resp.json()
    assert monitor["state"] == "PENDING"
    assert monitor["enabled"] is True
    mid = monitor["id"]
    assert len(client.get("/api/monitors").json()) == 1
    edited = client.patch(f"/api/monitors/{mid}", json={"name": "Production Gateway", "enabled": False}).json()
    assert edited["name"] == "Production Gateway"
    assert edited["enabled"] is False
    assert client.post(f"/api/monitors/{mid}/check").status_code == 409
    assert client.delete(f"/api/monitors/{mid}").status_code == 204
    assert client.get(f"/api/monitors/{mid}").status_code == 404
    assert client.get(f"/api/monitors/{mid}/history").status_code == 404


def test_validation_rejects_invalid_targets(client, monitor_payload):
    for url in ("ftp://example.com", "https://user:password@example.com", "not-a-url", "https://example.com:0"):
        payload = {**monitor_payload, "url": url}
        assert client.post("/api/monitors", json=payload).status_code == 422
    assert client.post("/api/monitors", json={**monitor_payload, "failure_threshold": 0}).status_code == 422
    assert client.post("/api/monitors", json={**monitor_payload, "method": "DELETE"}).status_code == 422
    assert client.post("/api/monitors", json={**monitor_payload, "unexpected": True}).status_code == 422


def test_api_key_guards_read_and_write(tmp_path, monitor_payload):
    app = create_app(Settings(database_path=tmp_path / "auth.db", scheduler_enabled=False, admin_token="secret-token"))
    with TestClient(app) as c:
        assert c.get("/healthz").status_code == 200
        assert c.get("/api/monitors").status_code == 401
        assert c.post("/api/monitors", json=monitor_payload).status_code == 401
        assert c.get("/metrics").status_code == 401
        assert c.post("/api/monitors", json=monitor_payload, headers={"X-API-Key": "secret-token"}).status_code == 201
        assert c.get("/api/monitors", headers={"X-API-Key": "secret-token"}).status_code == 200


def test_delete_nonexisting_monitor(client):
    assert client.delete("/api/monitors/9999").status_code == 404
    assert client.post("/api/incidents/9999/acknowledge").status_code == 404


def test_private_address_allowed_as_config_but_blocked_as_probe(client, monitor_payload):
    """Even an admin-created localhost monitor is blocked until explicitly enabled."""
    mid = client.post("/api/monitors", json={
        **monitor_payload, "url": "http://127.0.0.1:8888/health", "failure_threshold": 1,
    }).json()["id"]
    response = client.post(f"/api/monitors/{mid}/check")
    assert response.status_code == 200
    data = response.json()
    assert data["monitor"]["state"] == "DOWN"
    assert "blocked" in data["result"]["error"].lower()


def test_state_survives_app_restart(settings, monitor_payload):
    with TestClient(create_app(settings)) as c:
        monitor = c.post("/api/monitors", json=monitor_payload).json()
    with TestClient(create_app(settings)) as c:
        persisted = c.get(f"/api/monitors/{monitor['id']}").json()
        assert persisted["url"] == monitor_payload["url"]
        assert persisted["state"] == "PENDING"


def test_rejects_null_fields_and_records_pauses(client, monitor_payload):
    mid = client.post("/api/monitors", json=monitor_payload).json()["id"]
    assert client.patch(f"/api/monitors/{mid}", json={"name": None}).status_code == 422
    assert client.patch(f"/api/monitors/{mid}", json={"enabled": False}).status_code == 200
    stats = client.get("/api/overview").json()
    assert stats["paused"] == 1
    assert stats["pending"] == 0
