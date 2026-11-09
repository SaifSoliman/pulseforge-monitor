# API examples

> Examples assume `http://localhost:8000`. Add `-H 'X-API-Key: YOUR_TOKEN'` to commands if `ADMIN_TOKEN` is configured.

Create a monitor:

```bash
curl -X POST http://localhost:8000/api/monitors \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "Public API",
    "url": "https://api.example.org/health",
    "method": "GET",
    "expected_status": 200,
    "interval_seconds": 60,
    "timeout_seconds": 8,
    "failure_threshold": 2,
    "enabled": true
  }'
```

`api.example.org` is a placeholder — use a real endpoint that you own or are allowed to monitor.

Run a check immediately (replace `1` with the returned monitor ID):

```bash
curl -X POST http://localhost:8000/api/monitors/1/check
```

Read success metrics, history and incidents:

```bash
curl http://localhost:8000/api/overview
curl 'http://localhost:8000/api/monitors/1/history?limit=30'
curl 'http://localhost:8000/api/incidents?open_only=true'
curl http://localhost:8000/metrics
curl http://localhost:8000/api/notifications/status
curl -OJ 'http://localhost:8000/api/monitors/1/history.csv?limit=500'
curl -OJ 'http://localhost:8000/api/incidents.csv?limit=500'
```

Schedule maintenance (timestamps must include an offset; stored as UTC):

```bash
curl -X POST http://localhost:8000/api/monitors/1/maintenance \
  -H 'Content-Type: application/json' \
  -d '{"starts_at":"2026-11-10T01:00:00+00:00", "ends_at":"2026-11-10T02:00:00+00:00", "reason":"Database update"}'

curl http://localhost:8000/api/monitors/1/maintenance
# Replace 5 with the returned maintenance ID to cancel it.
curl -X DELETE http://localhost:8000/api/monitors/1/maintenance/5
```

A maintenance window does not stop checks. Incident history is retained; only new outage notifications are suppressed while the window is active. Persistent outages send one opening event on the first failed check after the interval. The start is inclusive and the end exclusive.

Pause or resume a monitor:

```bash
curl -X PATCH http://localhost:8000/api/monitors/1 \
  -H 'Content-Type: application/json' -d '{"enabled": false}'
```

Acknowledge an incident:

```bash
curl -X POST http://localhost:8000/api/incidents/1/acknowledge
```

Incident notifications are JSON POSTs shaped like this:

```json
{
  "event": "incident.opened",
  "monitor": {"id": 1, "name": "Public API", "url": "https://api.example.org/health"},
  "incident": {"id": 3, "started_at": "2026-11-09T12:30:00+00:00", "cause": "Expected HTTP 200; received HTTP 503"}
}
```

A recovery sends an `incident.resolved` event with the original incident ID and `resolved_at`. The HTTP server providing the webhook needs to accept generic JSON; this is not Slack's or Discord's specialized payload format by default.

## Notification delivery

With `ALERT_WEBHOOK_URL` configured, an incident transition and the corresponding outbox event are written in the same SQLite transaction. The app tries immediate delivery and retries failures after a backoff of 30, 60, 120 seconds and so on, capped at one hour. The scheduler must be enabled for retries to continue without manual checks.

Delivery is **at least once**. If the webhook receives an event but the app crashes before recording the success, the event may be delivered again. Consumers should use the combination of `event` and `incident.id` as an idempotency key.

Both CSV endpoints enforce the same `X-API-Key` requirement as their corresponding JSON endpoints. Exports are capped at 10,000 rows per request; spreadsheet-sensitive text is escaped.
