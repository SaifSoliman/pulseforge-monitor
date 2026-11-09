"""Small, transactional SQLite data layer with an auditable incident lifecycle."""

from contextlib import contextmanager
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from typing import Iterator

from .probe import ProbeResult


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def cutoff_hours(hours: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")


class Repository:
    def __init__(self, path: Path):
        self.path = Path(path)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=15000")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS monitors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    url TEXT NOT NULL,
                    method TEXT NOT NULL DEFAULT 'GET',
                    expected_status INTEGER NOT NULL DEFAULT 200,
                    interval_seconds INTEGER NOT NULL DEFAULT 60,
                    timeout_seconds INTEGER NOT NULL DEFAULT 8,
                    failure_threshold INTEGER NOT NULL DEFAULT 2,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    state TEXT NOT NULL DEFAULT 'PENDING',
                    consecutive_failures INTEGER NOT NULL DEFAULT 0,
                    last_checked_at TEXT,
                    last_latency_ms REAL,
                    last_http_status INTEGER,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS checks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    monitor_id INTEGER NOT NULL REFERENCES monitors(id) ON DELETE CASCADE,
                    checked_at TEXT NOT NULL,
                    ok INTEGER NOT NULL,
                    status_code INTEGER,
                    latency_ms REAL,
                    error TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_checks_monitor_date ON checks(monitor_id, checked_at DESC);
                CREATE TABLE IF NOT EXISTS incidents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    monitor_id INTEGER NOT NULL REFERENCES monitors(id) ON DELETE CASCADE,
                    started_at TEXT NOT NULL,
                    resolved_at TEXT,
                    acknowledged_at TEXT,
                    cause TEXT,
                    failed_checks INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_incidents_monitor_open ON incidents(monitor_id, resolved_at);
                CREATE TABLE IF NOT EXISTS notification_outbox (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    next_attempt_at TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    delivered_at TEXT,
                    last_error TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_outbox_pending ON notification_outbox(delivered_at, next_attempt_at);
            """)

    @staticmethod
    def _monitor_row(conn: sqlite3.Connection, monitor_id: int) -> dict | None:
        cutoff = cutoff_hours(24)
        row = conn.execute("""
            SELECT m.*,
              (SELECT ROUND(100.0 * SUM(c.ok) / COUNT(*), 1)
                 FROM checks c WHERE c.monitor_id=m.id AND c.checked_at >= ?) AS uptime_24h
            FROM monitors m WHERE m.id = ?
        """, (cutoff, monitor_id)).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["enabled"] = bool(item["enabled"])
        return item

    def create_monitor(self, data: dict) -> dict:
        now = utcnow()
        cols = ("name", "url", "method", "expected_status", "interval_seconds", "timeout_seconds", "failure_threshold", "enabled")
        with self.connection() as conn:
            cursor = conn.execute(
                f"INSERT INTO monitors ({', '.join(cols)}, created_at, updated_at) "
                f"VALUES ({', '.join('?' for _ in cols)}, ?, ?)",
                tuple(data[col] for col in cols) + (now, now),
            )
            item = self._monitor_row(conn, cursor.lastrowid)
            assert item is not None
            return item

    def list_monitors(self) -> list[dict]:
        with self.connection() as conn:
            ids = conn.execute("SELECT id FROM monitors ORDER BY created_at DESC, id DESC").fetchall()
            return [self._monitor_row(conn, row[0]) for row in ids]

    def get_monitor(self, monitor_id: int) -> dict | None:
        with self.connection() as conn:
            return self._monitor_row(conn, monitor_id)

    def update_monitor(self, monitor_id: int, changes: dict) -> dict | None:
        if not changes:
            return self.get_monitor(monitor_id)
        allowed = {"name", "url", "method", "expected_status", "interval_seconds", "timeout_seconds", "failure_threshold", "enabled"}
        if not changes.keys() <= allowed:
            raise ValueError("Invalid update fields")
        fields = dict(changes)
        fields["updated_at"] = utcnow()
        with self.connection() as conn:
            current = self._monitor_row(conn, monitor_id)
            if current is None:
                return None
            conn.execute(
                f"UPDATE monitors SET {', '.join(f'{key}=?' for key in fields)} WHERE id=?",
                (*fields.values(), monitor_id),
            )
            return self._monitor_row(conn, monitor_id)

    def delete_monitor(self, monitor_id: int) -> bool:
        with self.connection() as conn:
            cursor = conn.execute("DELETE FROM monitors WHERE id=?", (monitor_id,))
            return cursor.rowcount > 0

    def record_probe(self, monitor_id: int, result: ProbeResult, queue_notifications: bool = False) -> tuple[dict | None, dict | None]:
        """Atomically persist check + state change + incident; return notification on transition."""
        now = utcnow()
        notification = None
        with self.connection() as conn:
            monitor = self._monitor_row(conn, monitor_id)
            if monitor is None:
                return None, None
            conn.execute(
                "INSERT INTO checks(monitor_id,checked_at,ok,status_code,latency_ms,error) VALUES (?,?,?,?,?,?)",
                (monitor_id, now, int(result.ok), result.status_code, result.latency_ms, result.error),
            )
            failures = 0 if result.ok else monitor["consecutive_failures"] + 1
            state = monitor["state"]
            if result.ok:
                if state == "DOWN":
                    incident = conn.execute(
                        "SELECT * FROM incidents WHERE monitor_id=? AND resolved_at IS NULL ORDER BY id DESC LIMIT 1",
                        (monitor_id,),
                    ).fetchone()
                    if incident:
                        conn.execute("UPDATE incidents SET resolved_at=? WHERE id=?", (now, incident["id"]))
                        notification = {
                            "event": "incident.resolved",
                            "monitor": {"id": monitor_id, "name": monitor["name"], "url": monitor["url"]},
                            "incident": {"id": incident["id"], "started_at": incident["started_at"], "resolved_at": now},
                        }
                state = "UP"
            elif failures >= monitor["failure_threshold"]:
                if state != "DOWN":
                    cursor = conn.execute(
                        "INSERT INTO incidents(monitor_id,started_at,cause,failed_checks) VALUES (?,?,?,?)",
                        (monitor_id, now, result.error, failures),
                    )
                    notification = {
                        "event": "incident.opened",
                        "monitor": {"id": monitor_id, "name": monitor["name"], "url": monitor["url"]},
                        "incident": {"id": cursor.lastrowid, "started_at": now, "cause": result.error},
                    }
                else:
                    conn.execute("UPDATE incidents SET failed_checks=failed_checks+1 WHERE monitor_id=? AND resolved_at IS NULL", (monitor_id,))
                state = "DOWN"
            conn.execute("""
                UPDATE monitors SET state=?,consecutive_failures=?,last_checked_at=?,
                    last_http_status=?,last_latency_ms=?,last_error=? WHERE id=?
            """, (state, failures, now, result.status_code, result.latency_ms, result.error, monitor_id))
            if notification and queue_notifications:
                conn.execute(
                    "INSERT INTO notification_outbox(event,payload,created_at,next_attempt_at) VALUES (?,?,?,?)",
                    (notification["event"], json.dumps(notification, separators=(",", ":")), now, now),
                )
            return self._monitor_row(conn, monitor_id), notification

    def pending_notifications(self, limit: int = 20) -> list[dict]:
        """Return due events oldest first. A single scheduler instance owns dispatch."""
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT id, payload, attempts FROM notification_outbox "
                "WHERE delivered_at IS NULL AND next_attempt_at <= ? ORDER BY id ASC LIMIT ?",
                (utcnow(), limit),
            ).fetchall()
            return [{"id": row["id"], "payload": json.loads(row["payload"]), "attempts": row["attempts"]} for row in rows]

    def mark_notification_delivered(self, notification_id: int) -> None:
        with self.connection() as conn:
            conn.execute(
                "UPDATE notification_outbox SET delivered_at=?, attempts=attempts+1, last_error=NULL WHERE id=?",
                (utcnow(), notification_id),
            )

    def mark_notification_failed(self, notification_id: int, attempts: int, error: str) -> None:
        # Retry from 30 seconds, doubling until capped at one hour.
        delay = min(3600, 30 * (2 ** min(attempts, 7)))
        next_attempt = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat(timespec="seconds")
        with self.connection() as conn:
            conn.execute(
                "UPDATE notification_outbox SET attempts=attempts+1, next_attempt_at=?, last_error=? WHERE id=?",
                (next_attempt, error[:200], notification_id),
            )

    def outbox_summary(self) -> dict:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS total_pending, SUM(CASE WHEN attempts>0 THEN 1 ELSE 0 END) AS retrying "
                "FROM notification_outbox WHERE delivered_at IS NULL"
            ).fetchone()
            return {"pending": row["total_pending"], "retrying": row["retrying"] or 0}

    def history(self, monitor_id: int, limit: int = 50) -> list[dict]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT id,checked_at,ok,status_code,latency_ms,error FROM checks "
                "WHERE monitor_id=? ORDER BY id DESC LIMIT ?", (monitor_id, limit)
            ).fetchall()
            return [{**dict(row), "ok": bool(row["ok"])} for row in rows]

    def incidents(self, open_only: bool = False, limit: int = 100) -> list[dict]:
        predicate = "WHERE i.resolved_at IS NULL" if open_only else ""
        with self.connection() as conn:
            return [dict(row) for row in conn.execute(f"""
                SELECT i.*, m.name AS monitor_name, m.url AS monitor_url
                  FROM incidents i JOIN monitors m ON i.monitor_id=m.id
                  {predicate} ORDER BY i.started_at DESC, i.id DESC LIMIT ?
            """, (limit,)).fetchall()]

    def acknowledge_incident(self, incident_id: int) -> dict | None:
        now = utcnow()
        with self.connection() as conn:
            conn.execute(
                "UPDATE incidents SET acknowledged_at=COALESCE(acknowledged_at, ?) WHERE id=?",
                (now, incident_id),
            )
            row = conn.execute("""
                SELECT i.*, m.name AS monitor_name, m.url AS monitor_url FROM incidents i
                  JOIN monitors m ON m.id=i.monitor_id WHERE i.id=?
            """, (incident_id,)).fetchone()
            return dict(row) if row else None

    def overview(self) -> dict:
        with self.connection() as conn:
            rows = conn.execute("SELECT state, enabled, COUNT(*) AS n FROM monitors GROUP BY state, enabled").fetchall()
            counts = {"total": 0, "up": 0, "down": 0, "pending": 0, "paused": 0}
            for row in rows:
                counts["total"] += row["n"]
                if not row["enabled"]:
                    counts["paused"] += row["n"]
                else:
                    counts[row["state"].lower()] += row["n"]
            checks = conn.execute(
                "SELECT COUNT(*) AS total, SUM(ok) AS success FROM checks WHERE checked_at >= ?", (cutoff_hours(24),)
            ).fetchone()
            counts["checks_24h"] = checks["total"]
            counts["uptime_24h"] = round(100.0 * checks["success"] / checks["total"], 1) if checks["total"] else None
            counts["active_incidents"] = conn.execute("SELECT COUNT(*) FROM incidents WHERE resolved_at IS NULL").fetchone()[0]
            outbox = conn.execute(
                "SELECT COUNT(*) AS pending, SUM(CASE WHEN attempts > 0 THEN 1 ELSE 0 END) AS retrying "
                "FROM notification_outbox WHERE delivered_at IS NULL"
            ).fetchone()
            counts["notifications_pending"] = outbox["pending"]
            counts["notifications_retrying"] = outbox["retrying"] or 0
            return counts

    def due_monitor_ids(self) -> list[int]:
        now = datetime.now(timezone.utc)
        with self.connection() as conn:
            rows = conn.execute("SELECT id,interval_seconds,last_checked_at FROM monitors WHERE enabled=1").fetchall()
        due = []
        for row in rows:
            if row["last_checked_at"] is None:
                due.append(row["id"])
            else:
                last = datetime.fromisoformat(row["last_checked_at"])
                if (now - last).total_seconds() >= row["interval_seconds"]:
                    due.append(row["id"])
        return due

    def purge_history(self, retention_days: int) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat(timespec="seconds")
        with self.connection() as conn:
            return conn.execute("DELETE FROM checks WHERE checked_at < ?", (cutoff,)).rowcount

    def is_ready(self) -> bool:
        with self.connection() as conn:
            return conn.execute("SELECT 1").fetchone()[0] == 1
