"""Maintenance affects alert delivery, not observation or incident history."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import sqlite3
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.probe import ProbeResult


def time_window(start_offset=-5, end_offset=60):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    return {
        "starts_at": (now + timedelta(minutes=start_offset)).isoformat(),
        "ends_at": (now + timedelta(minutes=end_offset)).isoformat(),
        "reason": "  Database maintenance  ",
    }


def test_create_list_and_delete_window(client, monitor_payload):
    mid = client.post('/api/monitors', json=monitor_payload).json()['id']
    response = client.post(f'/api/monitors/{mid}/maintenance', json=time_window())
    assert response.status_code == 201
    window = response.json()
    assert window['reason'] == 'Database maintenance'
    assert window['active'] is True
    monitor = client.get(f'/api/monitors/{mid}').json()
    assert monitor['maintenance_active'] is True
    assert monitor['maintenance_until'] == window['ends_at']
    assert client.get('/api/overview').json()['in_maintenance'] == 1
    assert 'pulseforge_monitors_in_maintenance 1' in client.get('/metrics').text
    assert [w['id'] for w in client.get(f'/api/monitors/{mid}/maintenance').json()] == [window['id']]
    assert client.delete(f'/api/monitors/{mid}/maintenance/{window["id"]}').status_code == 204
    assert client.get(f'/api/monitors/{mid}').json()['maintenance_active'] is False
    assert client.delete(f'/api/monitors/{mid}/maintenance/{window["id"]}').status_code == 404


@pytest.mark.parametrize('mutate', [
    lambda w: {**w, 'starts_at': '2026-01-01T12:00:00'},  # missing timezone
    lambda w: {**w, 'ends_at': w['starts_at']},
    lambda w: {**w, 'starts_at': w['ends_at'], 'ends_at': w['starts_at']},
    lambda w: {**w, 'ends_at': (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()},
    lambda w: {**w, 'reason': 'x' * 201},
    lambda w: {**w, 'arbitrary': 'not allowed'},
])
def test_window_validation(client, monitor_payload, mutate):
    mid = client.post('/api/monitors', json=monitor_payload).json()['id']
    assert client.post(f'/api/monitors/{mid}/maintenance', json=mutate(time_window())).status_code == 422


def test_missing_monitors_and_cross_monitor_window_delete(client, monitor_payload):
    assert client.get('/api/monitors/9999/maintenance').status_code == 404
    assert client.post('/api/monitors/9999/maintenance', json=time_window()).status_code == 404
    first = client.post('/api/monitors', json=monitor_payload).json()['id']
    second = client.post('/api/monitors', json={**monitor_payload, 'name': 'Other API'}).json()['id']
    window = client.post(f'/api/monitors/{first}/maintenance', json=time_window()).json()
    assert client.delete(f'/api/monitors/{second}/maintenance/{window["id"]}').status_code == 404
    assert len(client.get(f'/api/monitors/{first}/maintenance').json()) == 1
    assert client.delete(f'/api/monitors/{first}').status_code == 204
    assert client.get(f'/api/monitors/{first}/maintenance').status_code == 404


def test_api_key_protects_window_mutations(settings, monitor_payload):
    with TestClient(create_app(replace(settings, admin_token='private-token'))) as client:
        headers = {'X-API-Key': 'private-token'}
        mid = client.post('/api/monitors', json=monitor_payload, headers=headers).json()['id']
        url = f'/api/monitors/{mid}/maintenance'
        assert client.get(url).status_code == 401
        assert client.post(url, json=time_window()).status_code == 401
        window = client.post(url, json=time_window(), headers=headers).json()
        assert client.delete(f'{url}/{window["id"]}').status_code == 401
        assert client.get(url, headers=headers).status_code == 200


def test_suppressed_outage_and_recovery_still_have_history(client, app, monitor_payload, monkeypatch):
    mid = client.post('/api/monitors', json={**monitor_payload, 'failure_threshold': 1}).json()['id']
    client.post(f'/api/monitors/{mid}/maintenance', json=time_window())
    monkeypatch.setattr('app.service.probe_target', AsyncMock(side_effect=[
        ProbeResult(False, 503, 10, 'Unavailable'),
        ProbeResult(True, 200, 12, None),
    ]))
    send = AsyncMock()
    monkeypatch.setattr(app.state.monitoring, 'send_notification', send)
    down = client.post(f'/api/monitors/{mid}/check').json()
    up = client.post(f'/api/monitors/{mid}/check').json()
    assert down['monitor']['state'] == 'DOWN'
    assert down['event'] is None
    assert up['monitor']['state'] == 'UP'
    assert up['event'] is None
    assert send.await_count == 0
    assert len(client.get(f'/api/monitors/{mid}/history').json()) == 2
    incident = client.get('/api/incidents').json()[0]
    assert incident['started_at'] and incident['resolved_at']
    assert incident['alerted_at'] is None


def test_window_boundary_and_persistent_outage_alert(client, app, monitor_payload, monkeypatch):
    mid = client.post('/api/monitors', json={**monitor_payload, 'failure_threshold': 1}).json()['id']
    t0 = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(minutes=5)
    start, end = t0.isoformat(), (t0 + timedelta(minutes=3)).isoformat()
    window = client.post(f'/api/monitors/{mid}/maintenance', json={
        'starts_at': start, 'ends_at': end,
    }).json()
    assert window['active'] is False
    monkeypatch.setattr('app.service.probe_target', AsyncMock(side_effect=[
        ProbeResult(False, 503, 4, 'No response'),
        ProbeResult(False, 503, 4, 'Still down'),
        ProbeResult(False, 503, 4, 'Still down'),
        ProbeResult(True, 200, 4, None),
    ]))
    send = AsyncMock()
    monkeypatch.setattr(app.state.monitoring, 'send_notification', send)
    # Inclusive start: the first failure is recorded but no alert is announced.
    monkeypatch.setattr('app.db.utcnow', lambda: start)
    first = client.post(f'/api/monitors/{mid}/check').json()
    assert first['event'] is None
    assert first['monitor']['maintenance_active'] is True
    # Exclusive end: still down triggers one delayed opening with original start.
    monkeypatch.setattr('app.db.utcnow', lambda: end)
    second = client.post(f'/api/monitors/{mid}/check').json()
    third = client.post(f'/api/monitors/{mid}/check').json()
    fourth = client.post(f'/api/monitors/{mid}/check').json()
    assert second['event'] == 'incident.opened'
    assert third['event'] is None
    assert fourth['event'] == 'incident.resolved'
    assert send.await_count == 2
    assert send.await_args_list[0].args[0]['incident']['started_at'] == start
    incident = client.get('/api/incidents').json()[0]
    assert incident['failed_checks'] == 3
    assert incident['alerted_at'] == end
    assert len(client.get(f'/api/monitors/{mid}/history').json()) == 4


def test_preexisting_announced_outage_resolves_during_maintenance(client, app, monitor_payload, monkeypatch):
    mid = client.post('/api/monitors', json={**monitor_payload, 'failure_threshold': 1}).json()['id']
    start_time = datetime.now(timezone.utc).replace(microsecond=0)
    start = (start_time + timedelta(minutes=5)).isoformat()
    client.post(f'/api/monitors/{mid}/maintenance', json={
        'starts_at': start, 'ends_at': (start_time + timedelta(minutes=20)).isoformat(),
    })
    monkeypatch.setattr('app.service.probe_target', AsyncMock(side_effect=[
        ProbeResult(False, 503, 1, 'Fail'), ProbeResult(True, 200, 1, None),
    ]))
    send = AsyncMock()
    monkeypatch.setattr(app.state.monitoring, 'send_notification', send)
    assert client.post(f'/api/monitors/{mid}/check').json()['event'] == 'incident.opened'
    monkeypatch.setattr('app.db.utcnow', lambda: start)
    assert client.post(f'/api/monitors/{mid}/check').json()['event'] == 'incident.resolved'
    assert send.await_count == 2


def test_windows_survive_restart_and_original_db_migrates(settings, monitor_payload):
    with TestClient(create_app(settings)) as c:
        mid = c.post('/api/monitors', json=monitor_payload).json()['id']
        window = c.post(f'/api/monitors/{mid}/maintenance', json=time_window()).json()
    # Simulate an existing v1.1 database, with an already announced incident but
    # no alerted_at column, while retaining maintenance records.
    with sqlite3.connect(settings.database_path) as conn:
        conn.execute('ALTER TABLE incidents RENAME TO incidents_old')
        conn.execute('''CREATE TABLE incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            monitor_id INTEGER NOT NULL REFERENCES monitors(id) ON DELETE CASCADE,
            started_at TEXT NOT NULL, resolved_at TEXT, acknowledged_at TEXT,
            cause TEXT, failed_checks INTEGER NOT NULL DEFAULT 0)''')
        conn.execute("INSERT INTO incidents(monitor_id,started_at,cause,failed_checks) VALUES (?,?,?,?)",
                     (mid, datetime.now(timezone.utc).isoformat(timespec='seconds'), 'Existing outage', 2))
        conn.execute('DROP TABLE incidents_old')
    with TestClient(create_app(settings)) as c:
        assert c.get(f'/api/monitors/{mid}/maintenance').json()[0]['id'] == window['id']
        assert c.get('/api/incidents').json()[0]['alerted_at'] is not None
    with TestClient(create_app(settings)) as c:
        assert c.get('/api/incidents').status_code == 200


def test_maintenance_keeps_outbox_silent_until_window_ends(settings, monitor_payload, monkeypatch):
    app = create_app(replace(settings, alert_webhook_url='https://hooks.example.org/alerts'))
    with TestClient(app) as c:
        mid = c.post('/api/monitors', json={**monitor_payload, 'failure_threshold': 1}).json()['id']
        t0 = datetime.now(timezone.utc).replace(microsecond=0)
        start = t0.isoformat()
        end = (t0 + timedelta(minutes=10)).isoformat()
        c.post(f'/api/monitors/{mid}/maintenance', json={'starts_at': start, 'ends_at': end})
        monkeypatch.setattr('app.service.probe_target', AsyncMock(return_value=ProbeResult(False, 503, 1, 'Outage')))
        deliver = AsyncMock(side_effect=OSError('Webhook temporarily unavailable'))
        monkeypatch.setattr(app.state.monitoring, 'send_notification', deliver)
        assert c.post(f'/api/monitors/{mid}/check').json()['event'] is None
        assert c.get('/api/notifications/status').json()['pending'] == 0
        monkeypatch.setattr('app.db.utcnow', lambda: end)
        assert c.post(f'/api/monitors/{mid}/check').json()['event'] == 'incident.opened'
        assert c.post(f'/api/monitors/{mid}/check').json()['event'] is None
        assert c.get('/api/notifications/status').json()['pending'] == 1
        assert deliver.await_count == 1  # Retry respects backoff, not every check.
