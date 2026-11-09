# Architecture & design decisions

## Components

- **FastAPI application (`app/main.py`)** exposes JSON API endpoints, generated OpenAPI docs, static assets and operational readiness endpoints. `create_app()` supports dependency injection for tests.
- **Monitoring service (`app/service.py`)** runs a single in-process polling scheduler; per-monitor `asyncio.Lock` serializes checks and a semaphore limits outbound concurrency to 10.
- **Probe engine (`app/probe.py`)** measures real response time, compares exact expected status codes, times out, and deliberately refuses redirects. HTTP proxy environment variables are not trusted.
- **Target gate (`app/security.py`)** resolves hostnames and blocks non-global IP addresses unless explicitly opted in. This is a defense in depth control, not comprehensive SSRF prevention: DNS rebinding between resolution and HTTP connection remains possible. Use egress firewall rules for untrusted installations.
- **Repository (`app/db.py`)** owns the SQLite database schema and atomic state transitions. SQLite uses WAL journaling and foreign keys. Probe results, incident transitions, and outgoing event enqueueing commit in one transaction.
- **Dashboard (`app/static/`)** is dependency-free JavaScript plus HTML/CSS. It polls the JSON API every 15 seconds and renders a monitor view, latency chart, incident history and forms.

## Persistence model

**monitors** stores each endpoint's configuration, current state (`PENDING`, `UP`, `DOWN`), failure streak and the latest HTTP result.

**checks** is an append-only-by-default event log of actual probes. It records timestamps, boolean success, status, latency and the error string. Rows older than the configured retention are purged by the scheduler.

**incidents** stores an incident per confirmed outage, with `started_at`, `resolved_at`, `acknowledged_at`, `cause`, `failed_checks` and `alerted_at`. The latter tracks whether an opening event was announced, not whether an external receiver processed it. Deleting a monitor cascades to its checks and incidents.

**maintenance_windows** stores a one-time half-open interval `[starts_at, ends_at)` and an optional reason per monitor, in UTC. Checks and incident transitions continue during maintenance. It changes only whether a *new* incident opening generates a notification.

**notification_outbox** stores serialized webhook events independently of the incident rows. Events are inserted in the same transaction as the state change, then delivered by an async dispatcher. Failed deliveries set a retry time (30 seconds doubling to a 1-hour cap); delivered events retain a delivery timestamp for investigation.

## State transitions

```text
PENDING -- successful probe ------------------------> UP
PENDING -- N consecutive failures ------------------> DOWN (new incident)
UP      -- fewer than N consecutive failures ------> UP (transient failure)
UP      -- N consecutive failures ------------------> DOWN (new incident)
DOWN    -- further failure -------------------------> DOWN (update failure count)
DOWN    -- successful probe ------------------------> UP (resolve incident)
```

A maintenance window is independent of the monitor's `UP`/`DOWN` state. New incidents started inside the interval have `alerted_at=NULL`. If a later failed check finds one of these incidents after maintenance, it marks `alerted_at` and announces the original outage exactly once. If the incident recovers before that happens, the incident closes without an alert. Previously announced outages still emit a resolution notification, even during maintenance, so downstream systems are not left with an active alert. Checks and history are always retained.

Paused monitors preserve their last known state but are not checked by the scheduler. A first successful probe clears the failure streak. Manual checks use the same transitions as scheduled checks.

## Schema upgrades

On startup, the repository creates the maintenance table if needed. For pre-1.2 databases it adds `incidents.alerted_at` and backfills existing incidents with their start time to avoid sending duplicate opening alerts on upgrade. The change is one-way; back up the SQLite file or volume before upgrading.

## Why SQLite and one worker?

SQLite offers zero-config durable local storage for a single-instance self-hosted application. WAL enables readers while checks are being recorded. One API process runs one scheduler, preventing unintended duplication. Running multiple Uvicorn workers or replicas will trigger duplicate checks; a proper distributed design should move scheduling into a worker queue with leased jobs and use PostgreSQL.

## Tradeoffs and failure cases

- Notification delivery uses an **at-least-once outbox** when `ALERT_WEBHOOK_URL` is configured. A process crash between remote receipt and local acknowledgement can lead to duplicate events; downstream consumers should deduplicate by the event and incident ID. The single-instance dispatcher avoids concurrent sends inside the process.
- An HTTP `302` fails a monitor expecting `200`, rather than following an unknown redirect into a potentially private network.
- Success percentage means *fraction of real successful checks over the last 24 hours*, not a time-weighted availability SLA. Sparse probes yield coarse estimates.
- Private targets are disabled by default and public target DNS is checked before connection. IP pinning and outbound policy are recommended for higher-trust deployments.
- Network timeouts and webhook delivery can affect due schedules by a few seconds. The scheduler intentionally prioritizes simplicity over real-time precision.
- Historical rows and incidents remain associated with the same monitor if you edit its URL. Use a new monitor to preserve a clean time series for a different service.
