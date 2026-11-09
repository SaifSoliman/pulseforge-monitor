"""Validated data transfer objects for the public HTTP API."""

from datetime import datetime, timedelta, timezone
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class MonitorCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=80)
    url: str = Field(min_length=10, max_length=2048)
    method: Literal["GET", "HEAD"] = "GET"
    expected_status: int = Field(default=200, ge=100, le=599)
    interval_seconds: int = Field(default=60, ge=30, le=3600)
    timeout_seconds: int = Field(default=8, ge=1, le=30)
    failure_threshold: int = Field(default=2, ge=1, le=10)
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        result = value.strip()
        if len(result) < 2:
            raise ValueError("Name must contain at least two non-whitespace characters")
        return result

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        from urllib.parse import urlsplit
        import ipaddress

        value = value.strip()
        try:
            parsed = urlsplit(value)
            port = parsed.port
        except ValueError as exc:
            raise ValueError("Invalid URL or port") from exc
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Only absolute http:// or https:// URLs are supported")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("Credentials must not appear in target URLs")
        if parsed.fragment:
            raise ValueError("URL fragments are not supported")
        if port == 0:
            raise ValueError("Invalid target port")
        hostname = parsed.hostname
        if hostname.endswith("."):
            raise ValueError("Trailing-dot hostnames are not supported")
        try:
            ipaddress.ip_address(hostname)
        except ValueError:
            if not hostname.isascii() or any(
                not label or not all(c.isalnum() or c == "-" for c in label)
                or label.startswith("-") or label.endswith("-")
                for label in hostname.split(".")
            ):
                raise ValueError("Invalid hostname") from None
        return value


class MonitorUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    url: str | None = None
    method: Literal["GET", "HEAD"] | None = None
    expected_status: int | None = Field(default=None, ge=100, le=599)
    interval_seconds: int | None = Field(default=None, ge=30, le=3600)
    timeout_seconds: int | None = Field(default=None, ge=1, le=30)
    failure_threshold: int | None = Field(default=None, ge=1, le=10)
    enabled: bool | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return MonitorCreate.normalize_name(value)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return MonitorCreate.validate_url(value)


class MaintenanceWindowCreate(BaseModel):
    """One-time UTC maintenance interval; start inclusive, end exclusive."""

    model_config = ConfigDict(extra="forbid")
    starts_at: datetime
    ends_at: datetime
    reason: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def validate_window(self):
        if self.starts_at.tzinfo is None or self.ends_at.tzinfo is None:
            raise ValueError("Start and end must include a timezone offset")
        self.starts_at = self.starts_at.astimezone(timezone.utc).replace(microsecond=0)
        self.ends_at = self.ends_at.astimezone(timezone.utc).replace(microsecond=0)
        if self.ends_at <= self.starts_at:
            raise ValueError("End must be after start")
        if self.ends_at <= datetime.now(timezone.utc):
            raise ValueError("Maintenance window must not have ended")
        if self.ends_at - self.starts_at > timedelta(days=7):
            raise ValueError("Maintenance windows cannot exceed seven days")
        self.reason = self.reason.strip()
        return self
