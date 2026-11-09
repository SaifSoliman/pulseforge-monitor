"""Webhook event delivery is durable across failed requests and process restarts."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import httpx
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.probe import ProbeResult


def test_failed_webhook_is_retried_and_delivered(tmp_path, monitor_payload, monkeypatch):
    settings = Settings(
        database_path=tmp_path / 'webhook.db', scheduler_enabled=False,
        alert_webhook_url='https://hooks.example.org/notify',
    )
    app = create_app(settings)
    delivery = AsyncMock(side_effect=httpx.ConnectTimeout('Unavailable'))
    monkeypatch.setattr(app.state.monitoring, 'send_notification', delivery)
    monkeypatch.setattr('app.service.probe_target', AsyncMock(return_value=ProbeResult(False, 503, 15, 'Unavailable')))
    with TestClient(app) as client:
        mid = client.post('/api/monitors', json={**monitor_payload, 'failure_threshold': 1}).json()['id']
        response = client.post(f'/api/monitors/{mid}/check')
        assert response.status_code == 200
        assert response.json()['event'] == 'incident.opened'
        assert client.get('/api/notifications/status').json() == {'pending': 1, 'retrying': 1}
        assert 'pulseforge_notifications_pending 1' in client.get('/metrics').text
        assert delivery.await_count == 1
        # Nothing is retried before its backoff expires.
        asyncio.run(app.state.monitoring.flush_notifications())
        assert delivery.await_count == 1

        with app.state.repository.connection() as conn:
            conn.execute('UPDATE notification_outbox SET next_attempt_at=? WHERE delivered_at IS NULL',
                         ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(timespec='seconds'),))
        delivery.side_effect = None
        asyncio.run(app.state.monitoring.flush_notifications())
        assert delivery.await_count == 2
        assert client.get('/api/notifications/status').json() == {'pending': 0, 'retrying': 0}
        with app.state.repository.connection() as conn:
            row = conn.execute('SELECT attempts, delivered_at, last_error FROM notification_outbox').fetchone()
            assert row['attempts'] == 2
            assert row['delivered_at'] is not None
            assert row['last_error'] is None


def test_unsent_notification_survives_restart(tmp_path, monitor_payload, monkeypatch):
    settings = Settings(
        database_path=tmp_path / 'persist.db', scheduler_enabled=False,
        alert_webhook_url='https://hooks.example.org/notify',
    )
    app1 = create_app(settings)
    monkeypatch.setattr(app1.state.monitoring, 'send_notification', AsyncMock(side_effect=httpx.ReadTimeout('offline')))
    monkeypatch.setattr('app.service.probe_target', AsyncMock(return_value=ProbeResult(False, 503, 3, 'Down')))
    with TestClient(app1) as client:
        mid = client.post('/api/monitors', json={**monitor_payload, 'failure_threshold': 1}).json()['id']
        assert client.post(f'/api/monitors/{mid}/check').status_code == 200

    app2 = create_app(settings)
    send = AsyncMock()
    monkeypatch.setattr(app2.state.monitoring, 'send_notification', send)
    with TestClient(app2) as client:
        assert client.get('/api/notifications/status').json()['pending'] == 1
        with app2.state.repository.connection() as conn:
            conn.execute('UPDATE notification_outbox SET next_attempt_at=? WHERE delivered_at IS NULL',
                         ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(timespec='seconds'),))
        asyncio.run(app2.state.monitoring.flush_notifications())
        assert send.await_count == 1
        assert send.await_args.args[0]['event'] == 'incident.opened'
        assert client.get('/api/notifications/status').json()['pending'] == 0
