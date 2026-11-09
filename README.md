<div align="center">

# ⌁ PulseForge

**Self-hosted uptime monitoring and incident response for developers and small teams.**

Run real HTTP checks. Detect outages. Acknowledge incidents. Track recovery. Own your data.

![Python](https://img.shields.io/badge/Python-3.11%2B-3673a5?style=flat-square&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/API-FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)
![Docker](https://img.shields.io/badge/Container-Docker-2496ed?style=flat-square&logo=docker&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-7293b3?style=flat-square)

</div>

> **Project status:** Early release (v1.1). HTTP checks, incident state transitions, CSV export and notification retry are implemented. Open engineering work is tracked in [the roadmap](docs/roadmap.md).

## Why this project exists

A single failed request doesn't necessarily mean an outage. PulseForge probes your endpoints on a schedule, persists check results to SQLite, and only opens an incident after a configurable number of consecutive failures. Once the service recovers, the open incident closes automatically and an optional outbound webhook can notify your team. Delivery failures are queued for retry rather than discarded.

This project is intentionally small enough to understand end-to-end but has production-minded considerations: state transitions, safe defaults for HTTP targets, API-key protection, a non-root Docker image, metrics for Prometheus, CI tests, retention policies and documented deployment boundaries.

### Key features

| Feature | What it does |
|---|---|
| Real HTTP monitors | GET/HEAD checks, expected status, timeout and configurable interval |
| Incident lifecycle | Opens after *N* failures; closes on recovery; supports acknowledgement |
| Historical performance | Timestamped checks, 24-hour success rate, latency chart and CSV export |
| Operational dashboard | Responsive, searchable and filterable interface; live 15-second refresh |
| Durable notifications | Webhook events stored transactionally with incidents; exponential-backoff retries |
| Automation-friendly API | CRUD, on-demand checks, history, incidents, Swagger at `/docs` |
| Metrics export | Prometheus-style `/metrics` endpoint and `/healthz`, `/readyz` |
| Deployable project | Docker Compose, Kubernetes single-replica sample, CI, tests |

## Get running

### Option 1 — Docker Compose

Requires Docker and Docker Compose.

```bash
git clone https://github.com/YOUR_USERNAME/pulseforge-monitor.git
cd pulseforge-monitor

docker compose up --build -d
```

Open **http://localhost:8000**. Data is stored in a persistent Docker volume. The port is bound to `127.0.0.1` by default so the dashboard isn't exposed to your LAN or internet.

### Option 2 — Local Python

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate             # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open **http://localhost:8000**. Data defaults to `var/pulseforge.db` (ignored by Git).

### Add your first monitor

Use the **+ Add monitor** button and enter a publicly accessible HTTP URL that you have permission to monitor, such as a health endpoint on a service you own. Set the expected HTTP response code (typically `200`). Checks start automatically and the dashboard updates every 15 seconds.

> Private IP ranges and localhost are blocked by default to reduce server-side request forgery (SSRF) exposure. Set `ALLOW_PRIVATE_TARGETS=true` **only in trusted environments** to monitor local or private services. This requires restarting the application.

## Reproduce the local outage/recovery demo

This is a real local HTTP test; no fake monitoring results are inserted into the database.

In terminal 1:

```bash
uvicorn scripts.demo_targets:app --port 9000
```

In terminal 2 (new environment settings):

```bash
ALLOW_PRIVATE_TARGETS=true uvicorn app.main:app --reload --port 8000
```

Create three monitors, all with expected status `200`, interval `30s` and failure threshold `2`:

| Monitor | URL | Initial response |
|---|---|---|
| Gateway API | `http://127.0.0.1:9000/health/api` | HTTP 200 |
| Payment service | `http://127.0.0.1:9000/health/payments` | HTTP 503 |
| Background worker | `http://127.0.0.1:9000/health/worker` | HTTP 200 |

Select **Run check now** twice for the payment monitor to open an incident. Restore it with:

```bash
curl -X POST http://127.0.0.1:9000/toggle/payments
```

Run another check. The outage closes automatically. Visit **Incidents** to see the recorded timeline.

When using Docker, `127.0.0.1:9000` *inside the container* is not the host demo server. Use `host.docker.internal` with the appropriate Docker host mapping or run both services on the same Docker network. The plain Python workflow above is simplest for this demo.

## API quick reference

| Verb | Endpoint | Purpose |
|---|---|---|
| GET | `/api/overview` | Aggregate check and monitor stats |
| GET / POST | `/api/monitors` | List and create monitors |
| GET / PATCH / DELETE | `/api/monitors/{id}` | Inspect, edit or delete a monitor |
| POST | `/api/monitors/{id}/check` | Run a real check immediately |
| GET | `/api/monitors/{id}/history` | Read recorded probe results |
| GET | `/api/monitors/{id}/history.csv` | Download recorded checks as CSV |
| GET | `/api/incidents?open_only=true` | See unresolved incidents |
| POST | `/api/incidents/{id}/acknowledge` | Record incident acknowledgement |
| GET | `/api/incidents.csv` | Download incident history as CSV |
| GET | `/api/notifications/status` | Pending and retrying webhook events |
| GET | `/metrics` | Prometheus text exposition |
| GET | `/healthz`, `/readyz` | Liveness and database readiness |

Interactive OpenAPI docs: **http://localhost:8000/docs**. More requests in [docs/api-examples.md](docs/api-examples.md).

## Configuration

Settings use environment variables; see [`.env.example`](.env.example).

| Variable | Default | Description |
|---|---|---|
| `DATABASE_PATH` | `var/pulseforge.db` | SQLite storage path; `/data/pulseforge.db` with Docker |
| `SCHEDULER_ENABLED` | `true` | Start the periodic probe scheduler |
| `SCHEDULER_TICK_SECONDS` | `10` | Scheduler polling cadence, minimum 5 seconds |
| `HISTORY_RETENTION_DAYS` | `30` | Probe history retention |
| `ALLOW_PRIVATE_TARGETS` | `false` | Permit local/private target addresses, for trusted installs only |
| `ADMIN_TOKEN` | empty | When set, required in the `X-API-Key` header for API and metrics |
| `ALERT_WEBHOOK_URL` | empty | Generic JSON POST destination on incident transitions |

The `.env.example` file is a **reference**; local Python doesn't automatically load it. Set/export variables in your shell. Docker Compose loads `.env` if you create one.

For an accessible production deployment, **set `ADMIN_TOKEN` and use TLS at a reverse proxy**. Keep the app on an internal network, restrict outbound network egress, and do not reuse the sample Kubernetes manifest without configuring secrets and an appropriate persistent volume. Full details: [security](docs/security.md).

## Development

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m ruff check app tests
```

CI runs tests, lint checks, and a Docker build on pushes and pull requests to `main`. The code has no frontend build step: HTML, CSS and JavaScript are served directly by FastAPI.

## How it works

```text
Dashboard ───► FastAPI API ───► SQLite (monitors, checks, incidents)
                      │                         │
                  scheduler                     └──► notification outbox
                      │                                      │
                      ├──► HTTP probes ───► incident change  └──► retry dispatcher
                      │                                      │
                      └──────────────────────────────────────┴──► webhook
```


For architecture, schema, concurrency and tradeoffs, see [docs/architecture.md](docs/architecture.md).

## Known limitations / roadmap

This is a working MVP, not a claim of enterprise-grade monitoring. It uses one scheduler process and SQLite; multi-instance deployments would duplicate checks. Monitoring is limited to HTTP GET/HEAD, with no TLS certificate-expiry checks, granular roles, or distributed probe agents. DNS-based SSRF checks reduce risk but cannot eliminate DNS rebinding without network-level egress restrictions.

Next planned work includes maintenance windows, monitor ownership/teams, delivery observability, a PostgreSQL + worker migration, per-monitor charts over longer windows, and richer deployments. See the [roadmap](docs/roadmap.md).

## Development and maintenance

The core application is intentionally single-instance: a scheduler runs endpoint checks, each result updates monitor and incident state transactionally, and outbound events are stored in a SQLite outbox for retry. The dashboard reads that state through the API rather than keeping a separate monitoring model.

See [architecture](docs/architecture.md) for decisions and limitations, [engineering notes](docs/engineering-notes.md) for the implementation boundaries, and [contributing](CONTRIBUTING.md) for local checks and changes. Planned work is tracked in the [roadmap](docs/roadmap.md).

## License

MIT. See [LICENSE](LICENSE).
