# Changelog

## 1.1 — 2026-11-09

- Persist webhook events in SQLite when incident state changes; retry failed deliveries with capped exponential backoff.
- Expose pending and retrying notification counts in the API and Prometheus endpoint.
- Export monitor checks and incident history as CSV with spreadsheet formula protection.
- Add CSV download controls to the dashboard and extend automated tests.
- Document delivery semantics, deployment trade-offs, and maintenance workflow.

## 1.0 — Initial working baseline

- HTTP checks, scheduler, incident lifecycle, SQLite storage, FastAPI API, responsive dashboard, Docker deployment and CI.
