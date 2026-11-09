"""PulseForge HTTP API and dashboard. Run: uvicorn app.main:app --reload"""

from contextlib import asynccontextmanager
import asyncio
import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from .config import Settings
from .db import Repository
from .export import encode_csv
from .models import MonitorCreate, MonitorUpdate
from .service import MonitoringService

STATIC = Path(__file__).parent / "static"


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings()
    repo = Repository(config.database_path)
    service = MonitoringService(repo, config)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        repo.initialize()
        task = asyncio.create_task(service.run_scheduler()) if config.scheduler_enabled else None
        try:
            yield
        finally:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    app = FastAPI(
        title="PulseForge API",
        description="Self-hosted HTTP uptime checks, outage incidents, acknowledgements, and history.",
        version="1.1.0",
        lifespan=lifespan,
    )
    app.state.repository = repo
    app.state.monitoring = service
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    def require_token(x_api_key: str | None = Header(default=None)) -> None:
        if config.admin_token and not (
            x_api_key is not None and secrets.compare_digest(x_api_key, config.admin_token)
        ):
            raise HTTPException(status_code=401, detail="Set a valid X-API-Key in Settings")

    @app.get("/", include_in_schema=False)
    async def dashboard():
        return FileResponse(STATIC / "index.html")

    @app.get("/healthz", tags=["Operations"])
    def health():
        return {"status": "ok", "service": "pulseforge"}

    @app.get("/readyz", tags=["Operations"])
    def ready():
        try:
            if repo.is_ready():
                return {"status": "ready"}
        except Exception:
            pass
        raise HTTPException(status_code=503, detail="Database not ready")

    @app.get("/api/overview", dependencies=[Depends(require_token)], tags=["Dashboard"])
    def overview():
        return repo.overview()

    @app.get("/api/monitors", dependencies=[Depends(require_token)], tags=["Monitors"])
    def monitors():
        return repo.list_monitors()

    @app.post("/api/monitors", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_token)], tags=["Monitors"])
    def create_monitor(payload: MonitorCreate):
        return repo.create_monitor(payload.model_dump())

    @app.get("/api/monitors/{monitor_id}", dependencies=[Depends(require_token)], tags=["Monitors"])
    def get_monitor(monitor_id: int):
        monitor = repo.get_monitor(monitor_id)
        if not monitor:
            raise HTTPException(status_code=404, detail="Monitor not found")
        return monitor

    @app.patch("/api/monitors/{monitor_id}", dependencies=[Depends(require_token)], tags=["Monitors"])
    def edit_monitor(monitor_id: int, payload: MonitorUpdate):
        changes = payload.model_dump(exclude_unset=True)
        if any(value is None for value in changes.values()):
            raise HTTPException(status_code=422, detail="Monitor fields cannot be null")
        monitor = repo.update_monitor(monitor_id, changes)
        if not monitor:
            raise HTTPException(status_code=404, detail="Monitor not found")
        return monitor

    @app.delete("/api/monitors/{monitor_id}", status_code=204, dependencies=[Depends(require_token)], tags=["Monitors"])
    def remove_monitor(monitor_id: int):
        if not repo.delete_monitor(monitor_id):
            raise HTTPException(status_code=404, detail="Monitor not found")
        return None

    @app.post("/api/monitors/{monitor_id}/check", dependencies=[Depends(require_token)], tags=["Monitors"])
    async def check_now(monitor_id: int):
        try:
            result = await service.check(monitor_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if not result:
            raise HTTPException(status_code=404, detail="Monitor not found")
        return result

    @app.get("/api/monitors/{monitor_id}/history", dependencies=[Depends(require_token)], tags=["Monitors"])
    def monitor_history(monitor_id: int, limit: int = Query(default=50, ge=1, le=500)):
        if not repo.get_monitor(monitor_id):
            raise HTTPException(status_code=404, detail="Monitor not found")
        return repo.history(monitor_id, limit)

    @app.get("/api/monitors/{monitor_id}/history.csv", dependencies=[Depends(require_token)], tags=["Monitors"])
    def export_monitor_history(monitor_id: int, limit: int = Query(default=1000, ge=1, le=10000)):
        if not repo.get_monitor(monitor_id):
            raise HTTPException(status_code=404, detail="Monitor not found")
        columns = ("id", "checked_at", "ok", "status_code", "latency_ms", "error")
        body = encode_csv(repo.history(monitor_id, limit), columns)
        return Response(body, media_type="text/csv; charset=utf-8", headers={
            "Content-Disposition": f'attachment; filename="pulseforge-monitor-{monitor_id}-history.csv"'
        })

    @app.get("/api/incidents.csv", dependencies=[Depends(require_token)], tags=["Incidents"])
    def export_incidents(limit: int = Query(default=1000, ge=1, le=10000)):
        columns = ("id", "monitor_name", "monitor_url", "started_at", "resolved_at", "acknowledged_at", "cause", "failed_checks")
        body = encode_csv(repo.incidents(limit=limit), columns)
        return Response(body, media_type="text/csv; charset=utf-8", headers={
            "Content-Disposition": 'attachment; filename="pulseforge-incidents.csv"'
        })

    @app.get("/api/incidents", dependencies=[Depends(require_token)], tags=["Incidents"])
    def list_incidents(open_only: bool = False, limit: int = Query(default=100, ge=1, le=500)):
        return repo.incidents(open_only=open_only, limit=limit)

    @app.post("/api/incidents/{incident_id}/acknowledge", dependencies=[Depends(require_token)], tags=["Incidents"])
    def acknowledge(incident_id: int):
        incident = repo.acknowledge_incident(incident_id)
        if not incident:
            raise HTTPException(status_code=404, detail="Incident not found")
        return incident

    @app.get("/api/notifications/status", dependencies=[Depends(require_token)], tags=["Operations"])
    def notification_status():
        return repo.outbox_summary()

    @app.get("/metrics", response_class=PlainTextResponse, dependencies=[Depends(require_token)], tags=["Operations"])
    def metrics():
        data = repo.overview()
        lines = [
            "# HELP pulseforge_monitors_total Total configured monitors.",
            "# TYPE pulseforge_monitors_total gauge",
            f"pulseforge_monitors_total {data['total']}",
            "# HELP pulseforge_monitors_down Monitors with confirmed outages.",
            "# TYPE pulseforge_monitors_down gauge",
            f"pulseforge_monitors_down {data['down']}",
            "# HELP pulseforge_incidents_active Unresolved incidents.",
            "# TYPE pulseforge_incidents_active gauge",
            f"pulseforge_incidents_active {data['active_incidents']}",
            "# HELP pulseforge_checks_24h Checks performed over the last 24 hours.",
            "# TYPE pulseforge_checks_24h gauge",
            f"pulseforge_checks_24h {data['checks_24h']}",
            "# HELP pulseforge_notifications_pending Webhook events awaiting delivery.",
            "# TYPE pulseforge_notifications_pending gauge",
            f"pulseforge_notifications_pending {data['notifications_pending']}",
            "# HELP pulseforge_notifications_retrying Webhook events scheduled for retry.",
            "# TYPE pulseforge_notifications_retrying gauge",
            f"pulseforge_notifications_retrying {data['notifications_retrying']}",
        ]
        return "\n".join(lines) + "\n"

    return app


app = create_app()
