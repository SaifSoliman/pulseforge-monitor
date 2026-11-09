"""Environment-backed application configuration."""

from dataclasses import dataclass, field
from pathlib import Path
import os


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_path: Path = field(default_factory=lambda: Path(os.getenv("DATABASE_PATH", "var/pulseforge.db")))
    scheduler_enabled: bool = field(default_factory=lambda: env_bool("SCHEDULER_ENABLED", True))
    scheduler_tick_seconds: int = field(default_factory=lambda: max(5, int(os.getenv("SCHEDULER_TICK_SECONDS", "10"))))
    history_retention_days: int = field(default_factory=lambda: max(1, int(os.getenv("HISTORY_RETENTION_DAYS", "30"))))
    allow_private_targets: bool = field(default_factory=lambda: env_bool("ALLOW_PRIVATE_TARGETS", False))
    admin_token: str = field(default_factory=lambda: os.getenv("ADMIN_TOKEN", ""))
    alert_webhook_url: str = field(default_factory=lambda: os.getenv("ALERT_WEBHOOK_URL", ""))
