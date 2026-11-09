# Engineering notes

These notes describe the implemented code paths and known boundaries of PulseForge.

## End-to-end request path

1. Monitor configuration enters through a validated FastAPI request and is stored in SQLite.
2. The scheduler picks due monitors; a per-monitor async lock prevents overlapping checks in the same application process.
3. An HTTP probe checks the configured target, measures latency, and compares the actual status to the expected status. Redirects are disabled.
4. A SQLite transaction stores the probe, updates the failure streak, and opens or closes an incident when the state changes.
5. If a webhook is configured, the same transaction inserts the incident event in `notification_outbox`.
6. The dispatcher delivers due events and records either success or the next retry time. The dashboard queries state over the API.

## Why this implementation

- **SQLite + a single scheduler process:** low operational overhead for a self-hosted personal deployment. The trade-off is that horizontal scale needs a separate worker and database.
- **Failure threshold:** prevents a single intermittent network failure from immediately opening an incident. The trade-off is a delay in outage detection.
- **Transaction-backed outbox:** preserves notifications when a destination is temporarily unavailable. Delivery is at least once, not exactly once.
- **HTTP redirects disabled:** avoids silently probing a redirected, potentially private destination.
- **CSV exports:** useful for ad hoc analysis and incident reviews. Row limits and spreadsheet formula escaping reduce operational and security risk.

## Verification

Run `python -m pytest -q` for state transitions, validation, token protection, CSV safety and webhook retry behavior. Run `python -m ruff check app tests` for lint. Use `scripts/demo_targets.py` to generate an actual 503-to-200 outage/recovery sequence in a local environment.

## Next engineering decisions

Maintenance windows and configuration audit trails are practical next increments. The more substantial architectural question is moving from a single process to leased probe workers and a durable external database without duplicating checks during failure and restart. See [roadmap](roadmap.md).
