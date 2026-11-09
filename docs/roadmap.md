# Engineering roadmap

The items below reflect current limitations and potential improvements. Each change should have a testable acceptance criterion and a documented trade-off.

## Implemented in v1.2

- [x] **Schedule one-time maintenance windows** per monitor, suppressing new alerts while continuing checks and incident history.
- [x] **Notify on sustained outages after maintenance** and close already-announced incidents even if they recover during maintenance.
- [x] **Cover UTC boundaries, validation and restarts** in automated tests.

## Implemented in v1.1

- [x] **Export monitor history and incidents to CSV**, with spreadsheet-formula protection for user-entered fields.
- [x] **Persist webhook notifications in an outbox** and retry failed deliveries with capped exponential backoff.
- [x] **Expose delivery backlog counters** through the operational API and Prometheus metrics.

## Near-term

- [ ] **Build per-monitor check charts** for 24h, 7d and 30d, including downsampling to avoid sending thousands of points to the frontend.
- [ ] **Implement configuration change audits** that track who changed target URLs, thresholds and enabled state.

## Medium-term (architectural upgrades)

- [ ] **Use PostgreSQL and an external scheduler worker** with leased jobs so horizontal API replicas don't duplicate checks.
- [ ] **Create per-team access controls** and service ownership for larger deployments.
- [ ] **Create TLS certificate expiry monitors** and DNS record health checks, with distinct probe types.
- [ ] **Add a Prometheus / Grafana deployment example** and integration tests for metric export.
- [ ] **Add webhook templates** for Slack, Discord and generic signed endpoints with a documented schema.

## High-value reliability work

- [ ] **Mitigate DNS rebinding fully** by resolving and connecting to pinned vetted addresses, preserving TLS SNI and hostname verification.
- [ ] **Add database migrations** and an upgrade test for preserving historical incidents across schema changes.
- [ ] **Document benchmark results** for 100/1,000 monitors, concurrency and database storage growth.

## Development workflow

For each improvement, define requirements and acceptance criteria, write focused tests, commit in reviewable stages, and record notable design decisions. A green CI run and a local demonstration should accompany behavior changes.
