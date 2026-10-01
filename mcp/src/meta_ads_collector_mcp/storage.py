"""Transactional storage and leases shared by stdio servers and workers."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any

from .schemas import Cancelled, MCPError


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))


class Store:
    def __init__(self, directory: str | Path):
        self.directory = Path(directory).expanduser().resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "state.sqlite3"
        with self.db() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, spec TEXT NOT NULL, state TEXT NOT NULL,
                    checkpoint TEXT NOT NULL DEFAULT '{}', stats TEXT NOT NULL DEFAULT '{}',
                    error TEXT, created REAL NOT NULL, updated REAL NOT NULL,
                    owner TEXT, lease REAL NOT NULL DEFAULT 0,
                    schedule_id TEXT, recovery TEXT NOT NULL DEFAULT 'fresh',
                    cancel INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS ads (
                    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    ad_id TEXT NOT NULL, record TEXT NOT NULL, created REAL NOT NULL,
                    newly_observed INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(job_id,ad_id)
                );
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL, data TEXT NOT NULL, created REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS events_job ON events(job_id,seq);
                CREATE TABLE IF NOT EXISTS profiles (name TEXT PRIMARY KEY, config TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS schedules (
                    id TEXT PRIMARY KEY, config TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
                    next_run REAL NOT NULL, active_job TEXT
                );
                CREATE TABLE IF NOT EXISTS observed (
                    schedule_id TEXT NOT NULL, ad_id TEXT NOT NULL, first_seen REAL NOT NULL,
                    PRIMARY KEY(schedule_id,ad_id)
                );
                CREATE TABLE IF NOT EXISTS workers (id TEXT PRIMARY KEY, heartbeat REAL NOT NULL);
            """)
        with suppress(OSError):
            self.path.chmod(0o600)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def create_job(self, spec: dict, schedule_id: str | None = None, db=None) -> str:
        job_id = uuid.uuid4().hex
        now = time.time()
        if db is None:
            with self.db() as connection:
                return self.create_job(spec, schedule_id, connection)
        db.execute(
            "INSERT INTO jobs(id,spec,state,created,updated,schedule_id) VALUES(?,?,'QUEUED',?,?,?)",
            (job_id, dumps(spec), now, now, schedule_id),
        )
        return job_id

    def job(self, job_id: str) -> dict:
        with self.db() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise MCPError("not_found", "Unknown job or result set")
            result = dict(row)
            for key in ("spec", "checkpoint", "stats"):
                result[key] = json.loads(result[key])
            if result["error"]:
                result["error"] = json.loads(result["error"])
            result["count"] = db.execute("SELECT count(*) FROM ads WHERE job_id=?", (job_id,)).fetchone()[0]
            return result

    def list_jobs(self, limit: int = 50, offset: int = 0) -> list[dict]:
        with self.db() as db:
            rows = db.execute("SELECT id FROM jobs ORDER BY created DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
        return [self.job(row[0]) for row in rows]

    def claim(self, job_id: str, owner: str, seconds: float = 30) -> bool:
        now = time.time()
        with self.db() as db:
            count = db.execute(
                """UPDATE jobs SET state='RUNNING',owner=?,lease=?,updated=?,
                recovery=CASE WHEN checkpoint<>'{}' THEN 'checkpoint_replay_with_dedup' ELSE recovery END
                WHERE id=? AND cancel=0 AND (state='QUEUED' OR
                (state IN ('RUNNING','PAUSED') AND (owner IS NULL OR lease<?)))""",
                (owner, now + seconds, now, job_id, now),
            ).rowcount
            return bool(count)

    def heartbeat(self, job_id: str, owner: str) -> bool:
        with self.db() as db:
            return bool(
                db.execute(
                    "UPDATE jobs SET lease=? WHERE id=? AND owner=? AND state IN ('RUNNING','PAUSED')",
                    (time.time() + 30, job_id, owner),
                ).rowcount
            )

    def update(self, job_id: str, owner: str, **values) -> None:
        allowed = {"checkpoint", "stats", "error", "state", "recovery"}
        if not values.keys() <= allowed:
            raise ValueError("Invalid update")
        columns = [f"{key}=?" for key in values]
        encoded = [
            dumps(value) if key in {"checkpoint", "stats", "error"} and value is not None else value
            for key, value in values.items()
        ]
        with self.db() as db:
            if not db.execute(
                f"UPDATE jobs SET {','.join(columns)},updated=? WHERE id=? AND owner=?",
                (*encoded, time.time(), job_id, owner),
            ).rowcount:
                raise MCPError("lease_lost", "Collection lease was lost")

    def release(self, job_id: str, owner: str, state: str) -> None:
        with self.db() as db:
            db.execute(
                "UPDATE jobs SET state=?,owner=NULL,lease=0,updated=? WHERE id=? AND owner=?",
                (state, time.time(), job_id, owner),
            )

    def save_ad(self, job_id: str, owner: str, record: dict) -> bool:
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            job = db.execute("SELECT owner,schedule_id,cancel FROM jobs WHERE id=?", (job_id,)).fetchone()
            if job is None or job["owner"] != owner:
                raise MCPError("lease_lost", "Collection lease was lost")
            if job["cancel"]:
                raise Cancelled()
            newly = False
            if job["schedule_id"]:
                newly = bool(
                    db.execute(
                        "INSERT OR IGNORE INTO observed VALUES(?,?,?)", (job["schedule_id"], record["id"], time.time())
                    ).rowcount
                )
            inserted = bool(
                db.execute(
                    "INSERT OR IGNORE INTO ads VALUES(?,?,?,?,?)",
                    (job_id, record["id"], dumps(record), time.time(), int(newly)),
                ).rowcount
            )
            db.execute("UPDATE jobs SET updated=? WHERE id=?", (time.time(), job_id))
            return inserted

    def records(
        self,
        job_id: str,
        limit: int | None = None,
        offset: int = 0,
        newly_only: bool = False,
        sort: str = "collected",
        descending: bool = False,
    ) -> list[dict]:
        self.job(job_id)
        sql = "SELECT record FROM ads WHERE job_id=?" + (" AND newly_observed=1" if newly_only else "")
        orders = {"collected": "rowid", "id": "ad_id", "start_date": "json_extract(record,'$.delivery_start_time')"}
        if sort not in orders:
            raise MCPError("invalid_sort", "Unsupported saved-result sort")
        sql += " ORDER BY " + orders[sort] + (" DESC" if descending else " ASC") + ",ad_id LIMIT ? OFFSET ?"
        with self.db() as db:
            return [json.loads(r[0]) for r in db.execute(sql, (job_id, limit if limit is not None else -1, offset))]

    def record(self, job_id: str, ad_id: str) -> dict:
        with self.db() as db:
            row = db.execute("SELECT record FROM ads WHERE job_id=? AND ad_id=?", (job_id, ad_id)).fetchone()
            if row is None:
                raise MCPError("not_found", "Ad does not belong to this collection")
            return json.loads(row[0])

    def ad_ids(self, job_id: str) -> list[str]:
        with self.db() as db:
            return [row[0] for row in db.execute("SELECT ad_id FROM ads WHERE job_id=?", (job_id,))]

    def replace_record(self, job_id: str, record: dict) -> None:
        with self.db() as db:
            if not db.execute(
                "UPDATE ads SET record=? WHERE job_id=? AND ad_id=?", (dumps(record), job_id, record["id"])
            ).rowcount:
                raise MCPError("not_found", "Ad does not belong to this collection")

    def event(self, job_id: str, kind: str, data: dict, owner: str | None = None) -> None:
        with self.db() as db:
            if owner is not None:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT owner FROM jobs WHERE id=?", (job_id,)).fetchone()
                if row is None or row[0] != owner:
                    return
            db.execute(
                "INSERT INTO events(job_id,kind,data,created) VALUES(?,?,?,?)", (job_id, kind, dumps(data), time.time())
            )

    def events(self, job_id: str, after: int = 0, limit: int = 100) -> list[dict]:
        self.job(job_id)
        with self.db() as db:
            return [
                dict(row) | {"data": json.loads(row["data"])}
                for row in db.execute(
                    "SELECT * FROM events WHERE job_id=? AND seq>? ORDER BY seq LIMIT ?", (job_id, after, limit)
                )
            ]

    def control(self, job_id: str, action: str) -> None:
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT state,owner,lease FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise MCPError("not_found", "Unknown job")
            if action == "cancel":
                if row[0] in ("COMPLETED", "LIMIT_REACHED", "FAILED", "CANCELLED"):
                    return
                db.execute(
                    """UPDATE jobs SET cancel=1,state=CASE WHEN state='RUNNING' THEN state ELSE 'CANCELLED' END,
                            updated=? WHERE id=?""",
                    (time.time(), job_id),
                )
            elif action == "resume":
                if row[0] not in ("PAUSED", "CANCELLED", "FAILED"):
                    raise MCPError("invalid_state", "Only paused, cancelled or failed jobs can resume")
                db.execute(
                    """UPDATE jobs SET cancel=0,state='QUEUED',error=NULL,recovery='checkpoint_replay_with_dedup',
                            updated=? WHERE id=?""",
                    (time.time(), job_id),
                )
            else:
                raise MCPError("invalid_action", "Unsupported job action")

    def delete(self, job_id: str) -> None:
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT state,owner,lease FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise MCPError("not_found", "Unknown collection")
            if row[0] in ("RUNNING", "QUEUED") or (row["owner"] and row["lease"] > time.time()):
                raise MCPError("job_active", "Cancel the job before deleting its results")
            db.execute("DELETE FROM jobs WHERE id=?", (job_id,))

    def setting(self, key: str, value: str | None = None) -> str | None:
        with self.db() as db:
            if value is not None:
                db.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (key, value))
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return row[0] if row else None

    def clear_setting(self, key: str) -> None:
        with self.db() as db:
            db.execute("DELETE FROM settings WHERE key=?", (key,))

    def profile(self, name: str) -> dict:
        with self.db() as db:
            row = db.execute("SELECT config FROM profiles WHERE name=?", (name,)).fetchone()
            if row is None:
                raise MCPError("unknown_proxy", "Unknown proxy profile")
            return json.loads(row[0])

    def save_profile(self, config: dict) -> None:
        with self.db() as db:
            db.execute("INSERT OR REPLACE INTO profiles VALUES(?,?)", (config["name"], dumps(config)))

    def profiles(self) -> list[dict]:
        with self.db() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT config FROM profiles ORDER BY name")]

    def pending(self, limit: int) -> list[str]:
        with self.db() as db:
            return [
                row[0]
                for row in db.execute(
                    """SELECT id FROM jobs WHERE cancel=0 AND
                (state='QUEUED' OR (state='RUNNING' AND lease<?)) ORDER BY created LIMIT ?""",
                    (time.time(), limit),
                )
            ]

    def schedules(self) -> list[dict]:
        with self.db() as db:
            return [dict(row) | {"config": json.loads(row["config"])} for row in db.execute("SELECT * FROM schedules")]

    def schedule(self, config: dict) -> str:
        schedule_id = uuid.uuid4().hex
        with self.db() as db:
            db.execute(
                "INSERT INTO schedules(id,config,next_run) VALUES(?,?,?)", (schedule_id, dumps(config), time.time())
            )
        return schedule_id

    def set_schedule(self, schedule_id: str, action: str) -> None:
        with self.db() as db:
            if action == "delete":
                count = db.execute("DELETE FROM schedules WHERE id=?", (schedule_id,)).rowcount
                db.execute("DELETE FROM observed WHERE schedule_id=?", (schedule_id,))
            else:
                count = db.execute(
                    "UPDATE schedules SET enabled=? WHERE id=?", (int(action == "enable"), schedule_id)
                ).rowcount
            if not count:
                raise MCPError("not_found", "Unknown schedule")

    def due(self) -> list[str]:
        now = time.time()
        created = []
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            for row in db.execute("SELECT * FROM schedules WHERE enabled=1 AND next_run<=?", (now,)).fetchall():
                active = db.execute("SELECT state FROM jobs WHERE id=?", (row["active_job"],)).fetchone()
                if active and active[0] in ("RUNNING", "QUEUED", "PAUSED"):
                    continue
                config = json.loads(row["config"])
                job_id = self.create_job(config["search"], row["id"], db)
                db.execute(
                    "UPDATE schedules SET next_run=?,active_job=? WHERE id=?",
                    (now + config["interval_seconds"], job_id, row["id"]),
                )
                created.append(job_id)
                cutoff = now - config["retention_days"] * 86400
                db.execute(
                    "DELETE FROM jobs WHERE schedule_id=? AND updated<? AND state NOT IN ('RUNNING','QUEUED','PAUSED')",
                    (row["id"], cutoff),
                )
        return created

    def worker_heartbeat(self, owner: str, remove: bool = False) -> None:
        with self.db() as db:
            if remove:
                db.execute("DELETE FROM workers WHERE id=?", (owner,))
            else:
                db.execute("INSERT OR REPLACE INTO workers VALUES(?,?)", (owner, time.time()))

    def worker_alive(self) -> bool:
        with self.db() as db:
            return bool(db.execute("SELECT 1 FROM workers WHERE heartbeat>?", (time.time() - 30,)).fetchone())
