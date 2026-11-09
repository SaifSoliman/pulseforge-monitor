from unittest.mock import AsyncMock

from app.probe import ProbeResult


def test_outage_acknowledgement_and_recovery(client, app, monitor_payload, monkeypatch):
    mid = client.post("/api/monitors", json=monitor_payload).json()["id"]
    mock = AsyncMock(side_effect=[
        ProbeResult(True, 200, 25.5, None),
        ProbeResult(False, 503, 16, "Expected HTTP 200; received HTTP 503"),
        ProbeResult(False, 503, 17, "Expected HTTP 200; received HTTP 503"),
        ProbeResult(False, 503, 18, "Expected HTTP 200; received HTTP 503"),
        ProbeResult(True, 200, 19, None),
    ])
    monkeypatch.setattr("app.service.probe_target", mock)
    notify = AsyncMock()
    monkeypatch.setattr(app.state.monitoring, "send_notification", notify)
    calls = [client.post(f"/api/monitors/{mid}/check").json() for _ in range(5)]
    assert [call["monitor"]["state"] for call in calls] == ["UP", "UP", "DOWN", "DOWN", "UP"]
    assert [call["event"] for call in calls] == [None, None, "incident.opened", None, "incident.resolved"]
    assert notify.await_count == 2
    incidents = client.get("/api/incidents").json()
    assert len(incidents) == 1
    incident = incidents[0]
    assert incident["resolved_at"] is not None
    assert incident["failed_checks"] == 3
    acknowledged = client.post(f"/api/incidents/{incident['id']}/acknowledge").json()
    assert acknowledged["acknowledged_at"] is not None
    assert client.get("/api/incidents?open_only=true").json() == []
    history = client.get(f"/api/monitors/{mid}/history").json()
    assert len(history) == 5
    assert sum(item["ok"] for item in history) == 2
    assert client.get("/api/overview").json()["uptime_24h"] == 40.0
    assert "pulseforge_monitors_total 1" in client.get("/metrics").text


def test_down_state_from_first_failure(client, app, monitor_payload, monkeypatch):
    mid = client.post("/api/monitors", json={**monitor_payload, "failure_threshold": 1}).json()["id"]
    monkeypatch.setattr("app.service.probe_target", AsyncMock(return_value=ProbeResult(False, None, 2, "Connection refused")))
    result = client.post(f"/api/monitors/{mid}/check").json()
    assert result["event"] == "incident.opened"
    assert result["monitor"]["state"] == "DOWN"
    assert len(client.get("/api/incidents?open_only=true").json()) == 1
    assert client.get("/api/overview").json()["active_incidents"] == 1


def test_manual_check_notifies_only_on_transitions(client, app, monitor_payload, monkeypatch):
    mid = client.post("/api/monitors", json={**monitor_payload, "failure_threshold": 1}).json()["id"]
    monkeypatch.setattr("app.service.probe_target", AsyncMock(side_effect=[
        ProbeResult(False, 503, 1, "Unavailable"),
        ProbeResult(False, 503, 1, "Still unavailable"),
        ProbeResult(True, 200, 1, None),
    ]))
    notify = AsyncMock()
    monkeypatch.setattr(app.state.monitoring, "send_notification", notify)
    for _ in range(3):
        assert client.post(f"/api/monitors/{mid}/check").status_code == 200
    events = [call.args[0]["event"] for call in notify.await_args_list]
    assert events == ["incident.opened", "incident.resolved"]
