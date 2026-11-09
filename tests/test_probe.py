import asyncio

import httpx
import pytest

from app.probe import probe_target
from app.security import UnsafeTargetError, ensure_safe_target


@pytest.mark.parametrize("host", ["127.0.0.1", "192.168.1.1", "169.254.169.254", "10.0.0.3", "::1"])
def test_private_ip_rejected(host):
    url = f"http://[{host}]/" if ":" in host else f"http://{host}/"
    with pytest.raises(UnsafeTargetError):
        asyncio.run(ensure_safe_target(url, False))


def test_private_targets_allowed_when_explicitly_opted_in():
    asyncio.run(ensure_safe_target("http://127.0.0.1:9999", True))


def test_dns_resolution_filters_private(monkeypatch):
    monkeypatch.setattr("app.security._resolve_host", lambda host, port: {"8.8.8.8", "10.1.1.1"})
    with pytest.raises(UnsafeTargetError):
        asyncio.run(ensure_safe_target("https://example.com", False))


def test_probe_expected_status_and_redirect_not_followed(monkeypatch):
    async def handler(request):
        return httpx.Response(302, headers={"Location": "http://localhost/private"})

    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    monkeypatch.setattr("app.probe.httpx.AsyncClient", factory)
    response = asyncio.run(probe_target("https://example.com", "GET", 200, 5, True))
    assert response.ok is False
    assert response.status_code == 302


def test_nonmatching_status_is_not_counted_as_success(monkeypatch):
    async def handler(request):
        return httpx.Response(204)

    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    monkeypatch.setattr("app.probe.httpx.AsyncClient", factory)
    assert asyncio.run(probe_target("https://example.com", "HEAD", 204, 5, True)).ok
