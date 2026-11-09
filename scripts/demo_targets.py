"""Local test targets for trying the real monitoring workflow.

Start with: uvicorn scripts.demo_targets:app --port 9000
Set ALLOW_PRIVATE_TARGETS=true for the PulseForge instance used for this demo.
Do not expose this demo server on a public network.
"""

import asyncio
from fastapi import FastAPI, HTTPException

app = FastAPI(title="PulseForge local demo targets")
health = {"payments": False, "api": True, "worker": True}


@app.get("/health/{service}")
async def healthcheck(service: str):
    if service not in health:
        raise HTTPException(404, "Unknown service")
    if not health[service]:
        raise HTTPException(503, f"{service} is unavailable")
    if service == "worker":
        await asyncio.sleep(0.12)
    return {"service": service, "status": "healthy"}


@app.post("/toggle/{service}")
def toggle(service: str):
    if service not in health:
        raise HTTPException(404, "Unknown service")
    health[service] = not health[service]
    return {"service": service, "healthy": health[service]}
