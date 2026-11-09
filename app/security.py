"""Conservative target validation to reduce SSRF exposure.

Important: DNS can change between validation and connection; for untrusted public
installations enforce outbound network rules at the infrastructure layer too.
"""

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit


class UnsafeTargetError(ValueError):
    pass


def _resolve_host(host: str, port: int) -> set[str]:
    result = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP, type=socket.SOCK_STREAM)
    return {entry[4][0] for entry in result}


async def ensure_safe_target(url: str, allow_private_targets: bool) -> None:
    parsed = urlsplit(url)
    host = parsed.hostname
    if not host:
        raise UnsafeTargetError("Target host is required")
    if allow_private_targets:
        return
    if host.lower() in {"localhost", "localhost.localdomain"} or host.lower().endswith(".localhost"):
        raise UnsafeTargetError("Local or private network targets are blocked")
    try:
        addresses = await asyncio.to_thread(_resolve_host, host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise UnsafeTargetError(f"DNS lookup failed: {exc.strerror or 'unknown host'}") from exc
    if not addresses:
        raise UnsafeTargetError("Target did not resolve to an IP address")
    for addr in addresses:
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError as exc:
            raise UnsafeTargetError("DNS returned an invalid IP address") from exc
        if not ip.is_global:
            raise UnsafeTargetError("Private, loopback and reserved IP addresses are blocked")
