"""Export API regressions, including spreadsheet formula injection safety."""

import csv
from io import StringIO
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.probe import ProbeResult


def test_monitor_history_csv(client, monitor_payload, monkeypatch):
    mid = client.post('/api/monitors', json=monitor_payload).json()['id']
    monkeypatch.setattr('app.service.probe_target', AsyncMock(return_value=ProbeResult(True, 200, 12.3, None)))
    assert client.post(f'/api/monitors/{mid}/check').status_code == 200
    result = client.get(f'/api/monitors/{mid}/history.csv')
    assert result.status_code == 200
    assert result.headers['content-type'].startswith('text/csv')
    assert 'attachment;' in result.headers['content-disposition']
    rows = list(csv.DictReader(StringIO(result.text)))
    assert len(rows) == 1
    assert rows[0]['status_code'] == '200'
    assert rows[0]['ok'] == 'true'
    assert client.get('/api/monitors/12345/history.csv').status_code == 404
    assert client.get(f'/api/monitors/{mid}/history.csv?limit=10001').status_code == 422


def test_incident_export_escapes_spreadsheet_formulas(client, monitor_payload, monkeypatch):
    payload = {**monitor_payload, 'name': '=SUM(2,2)', 'failure_threshold': 1}
    mid = client.post('/api/monitors', json=payload).json()['id']
    monkeypatch.setattr('app.service.probe_target', AsyncMock(return_value=ProbeResult(False, 500, 2, '=HYPERLINK("evil")')))
    assert client.post(f'/api/monitors/{mid}/check').status_code == 200
    result = client.get('/api/incidents.csv')
    assert result.status_code == 200
    row = next(csv.DictReader(StringIO(result.text)))
    assert row['monitor_name'] == "'=SUM(2,2)"
    assert row['cause'] == "'=HYPERLINK(\"evil\")"
    assert row['monitor_url'] == monitor_payload['url']
    assert result.headers['content-disposition'].endswith('"pulseforge-incidents.csv"')


def test_export_requires_admin_token(tmp_path, monitor_payload):
    settings = Settings(database_path=tmp_path / 'secure.db', scheduler_enabled=False, admin_token='secret')
    with TestClient(create_app(settings)) as client:
        mid = client.post('/api/monitors', json=monitor_payload, headers={'X-API-Key': 'secret'}).json()['id']
        assert client.get('/api/incidents.csv').status_code == 401
        assert client.get(f'/api/monitors/{mid}/history.csv').status_code == 401
        assert client.get('/api/notifications/status').status_code == 401
        assert client.get('/api/incidents.csv', headers={'X-API-Key': 'secret'}).status_code == 200


def test_formula_safety_on_whitespace_prefixed_fields():
    from app.export import encode_csv

    output = encode_csv([{'v': '   =2+2'}, {'v': '\t@cmd'}, {'v': '-2'}, {'v': 'ordinary text'}], ('v',))
    rows = list(csv.DictReader(StringIO(output)))
    assert [r['v'] for r in rows] == ["'   =2+2", "'\t@cmd", "'-2", 'ordinary text']
