# Changelog

## 1.2 — 2026-11-09

- Add per-monitor maintenance windows with timezone-aware start/end input, an optional reason and automatic status reporting.
- Continue recording checks and incident transitions during maintenance, but suppress new outage alerts. Announce an outage if it is still active once the window ends.
- Send recovery notifications for previously announced incidents, including recoveries during maintenance.
- Add a backward-compatible database migration and monitor detail controls for scheduling and removing windows.
- Expand test coverage around maintenance boundaries, incident transitions, access control and persistence.

## 1.1 — 2026-11-09

- Persist webhook events in SQLite when incident state changes; retry failed deliveries with capped exponential backoff.
- Expose pending and retrying notification counts in the API and Prometheus endpoint.
- Export monitor checks and incident history as CSV with spreadsheet formula protection.
- Add CSV download controls to the dashboard and extend automated tests.
- Document delivery semantics, deployment trade-offs, and maintenance workflow.

## 1.0 — Initial working baseline

- HTTP checks, scheduler, incident lifecycle, SQLite storage, FastAPI API, responsive dashboard, Docker deployment and CI.
