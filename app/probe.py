"""Real network checks. No simulated uptime values are used."""

import time
from dataclasses import dataclass

import httpx

from .security import UnsafeTargetError, ensure_safe_target


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    status_code: int | None
    latency_ms: float | None
    error: str | None


async def probe_target(
    url: str,
    method: str,
    expected_status: int,
    timeout_seconds: int,
    allow_private_targets: bool,
) -> ProbeResult:
    start = time.perf_counter()
    try:
        await ensure_safe_target(url, allow_private_targets)
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=False,
            trust_env=False,
            headers={"User-Agent": "PulseForge/1.0 (self-hosted availability monitor)"},
        ) as client:
            response = await client.request(method, url)
        latency = round((time.perf_counter() - start) * 1000, 1)
        ok = response.status_code == expected_status
        error = None if ok else f"Expected HTTP {expected_status}; received HTTP {response.status_code}"
        return ProbeResult(ok=ok, status_code=response.status_code, latency_ms=latency, error=error)
    except (httpx.HTTPError, UnsafeTargetError, OSError, ValueError) as exc:
        return ProbeResult(ok=False, status_code=None, latency_ms=round((time.perf_counter() - start) * 1000, 1), error=str(exc)[:500] or type(exc).__name__)
