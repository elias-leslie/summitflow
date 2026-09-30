"""Host-local durable transport spool. Agent Hub alone owns receipt checkpoints."""

from __future__ import annotations

import fcntl
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4


class OutboxFull(RuntimeError):
    pass


class ManagedOutbox:
    """One SQLite writer per operation; full fsync before capture is acknowledged.

    Quota and acknowledged raw retention are explicit operator inputs. Unaccepted
    evidence never expires; quota exhaustion records a gap and fails capture.
    """

    def __init__(self, path: Path, *, max_bytes: int, retention_seconds: int):
        if max_bytes <= 0 or retention_seconds < 0:
            raise ValueError("Explicit positive outbox quota and nonnegative retention are required")
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(path.parent, 0o700)
        self.path = path
        self.max_bytes = max_bytes
        self.retention_seconds = retention_seconds
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        os.chmod(path, 0o600)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS owner (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1), producer TEXT NOT NULL,
                    epoch TEXT NOT NULL, health TEXT NOT NULL, gaps INTEGER NOT NULL DEFAULT 0,
                    delivery_health TEXT NOT NULL DEFAULT 'pending',
                    capture_disabled INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS threads (
                    id TEXT PRIMARY KEY, project TEXT NOT NULL, registration TEXT NOT NULL,
                    next_position INTEGER NOT NULL DEFAULT 1,
                    source_id TEXT, acknowledged INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS events (
                    thread TEXT NOT NULL REFERENCES threads(id), position INTEGER NOT NULL,
                    observation TEXT, byte_size INTEGER NOT NULL, accepted_at REAL,
                    disposition TEXT, issue TEXT, PRIMARY KEY(thread, position)
                );
                CREATE TABLE IF NOT EXISTS quarantine (
                    id TEXT PRIMARY KEY, payload TEXT NOT NULL, byte_size INTEGER NOT NULL
                );
            """)
            db.execute("INSERT OR IGNORE INTO owner(singleton,producer,epoch,health) VALUES(1,?,?,?)", (str(uuid4()), str(uuid4()), "new"))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA journal_mode=DELETE")
        db.execute("PRAGMA secure_delete=ON")
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    @contextmanager
    def lease(self):
        """Process lifetime ownership, not PID inference or takeover of native sessions."""
        fd = os.open(str(self.path) + ".owner-lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        finally:
            os.close(fd)

    @contextmanager
    def delivery_lease(self):
        fd = os.open(str(self.path) + ".delivery-lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        finally:
            os.close(fd)

    def owner(self) -> dict:
        with self.connect() as db:
            return dict(db.execute("SELECT * FROM owner WHERE singleton=1").fetchone())

    def health(self, state: str, *, gap: bool = False):
        with self.connect() as db:
            db.execute("UPDATE owner SET health=?, gaps=gaps+? WHERE singleton=1", (state, int(gap)))

    def delivery_health(self, state: str):
        with self.connect() as db:
            db.execute("UPDATE owner SET delivery_health=? WHERE singleton=1", (state,))

    def disable_capture(self):
        with self.connect() as db:
            db.execute("UPDATE owner SET capture_disabled=1,health='disabled' WHERE singleton=1")

    def quarantine(self, payload: dict):
        """Retain an unsupported unbound wire frame without inventing a subject."""
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        size = len(encoded.encode())
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._cleanup(db)
            used = self._used_bytes(db)
            if used + size > self.max_bytes:
                raise OutboxFull("Unbound capture exceeds quota")
            db.execute("INSERT INTO quarantine(id,payload,byte_size) VALUES(?,?,?)", (str(uuid4()), encoded, size))

    def add_thread(self, thread: str, project: str, registration: dict):
        encoded = json.dumps(registration, sort_keys=True, separators=(",", ":"))
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT project,registration FROM threads WHERE id=?", (thread,)).fetchone()
            if existing and (existing["project"], existing["registration"]) != (project, encoded):
                raise ValueError("Managed thread binding is immutable")
            self._cleanup(db)
            if not existing and self._used_bytes(db) + len((thread + project + encoded).encode()) > self.max_bytes:
                raise OutboxFull("Managed ownership registry exceeds quota")
            db.execute("INSERT OR IGNORE INTO threads(id,project,registration) VALUES(?,?,?)", (thread, project, encoded))

    def threads(self) -> list[dict]:
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM threads ORDER BY id")]

    def capture(self, thread: str, *, kind: str, payload: dict, reference: dict | None = None) -> int:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._cleanup(db)
            row = db.execute("SELECT next_position FROM threads WHERE id=?", (thread,)).fetchone()
            if row is None:
                raise ValueError("Only explicitly owned threads can be captured")
            position = row[0]
            origin = "live"
            if kind == "app_server_snapshot":
                origin = "active_resume_snapshot" if payload.get("method") == "thread/resume" else "stored_snapshot"
            observation = {"position": position, "thread_id": thread, "origin": origin, "kind": kind, "payload": payload, "source_reference": reference or {}}
            encoded = json.dumps(observation, sort_keys=True, separators=(",", ":"))
            size = len(encoded.encode())
            used = self._used_bytes(db)
            if used + size > self.max_bytes:
                db.execute("UPDATE owner SET health='outbox_full',gaps=gaps+1 WHERE singleton=1")
                db.commit()
                raise OutboxFull("Managed capture quota exhausted; rollout recovery required")
            db.execute("INSERT INTO events(thread,position,observation,byte_size) VALUES(?,?,?,?)", (thread, position, encoded, size))
            db.execute("UPDATE threads SET next_position=next_position+1 WHERE id=?", (thread,))
            return position

    def pending(self, thread: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT observation FROM events WHERE thread=? AND accepted_at IS NULL ORDER BY position LIMIT 1", (thread,)).fetchone()
            return json.loads(row[0]) if row else None

    def bind_source(self, thread: str, receipt: dict):
        with self.connect() as db:
            row = db.execute("SELECT source_id,next_position,acknowledged FROM threads WHERE id=?", (thread,)).fetchone()
            if receipt.get("schema_version") != "native-observation.v1" or receipt.get("authenticity") != "collector_attested":
                raise ValueError("Unexpected Agent Hub source acknowledgement")
            if row["source_id"] not in (None, receipt["source_id"]):
                raise ValueError("Agent Hub source identity changed")
            # Registration cannot acknowledge pending local payloads. Only their
            # exact accepted/replayed dispositions permit outbox cleanup.
            if not 0 <= receipt["committed_position"] < row["next_position"]:
                raise ValueError("Agent Hub returned an impossible source position")
            db.execute("UPDATE threads SET source_id=? WHERE id=?", (receipt["source_id"], thread))

    def accept(self, thread: str, position: int, result: dict) -> bool:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM threads WHERE id=?", (thread,)).fetchone()
            if result.get("schema_version") != "native-observation.v1" or result.get("source_id") != row["source_id"] or result.get("authenticity") != "collector_attested":
                raise ValueError("Agent Hub acknowledgement binding mismatch")
            committed = result["committed_position"]
            if not 0 <= committed < row["next_position"]:
                raise ValueError("Agent Hub acknowledgement exceeds captured positions")
            dispositions = result.get("dispositions", [])
            if len(dispositions) != 1 or dispositions[0]["position"] != position:
                raise ValueError("Agent Hub acknowledgement does not name the sent receipt")
            disposition = dispositions[0]
            if disposition["disposition"] == "conflict":
                db.execute("UPDATE events SET disposition=?,issue=? WHERE thread=? AND position=?", ("conflict", disposition.get("issue_code"), thread, position))
                db.execute("UPDATE owner SET delivery_health='receipt_conflict' WHERE singleton=1")
                return False
            if disposition["disposition"] not in {"replayed", "retained", "accounted", "reconciled", "unresolved", "unsupported", "inherited"}:
                raise ValueError("Unknown Agent Hub disposition")
            if committed < position or committed < row["acknowledged"]:
                db.execute("UPDATE owner SET delivery_health='acknowledgement_gap' WHERE singleton=1")
                return False
            db.execute("UPDATE events SET accepted_at=?,disposition=?,issue=? WHERE thread=? AND position=?", (time.time(), disposition["disposition"], disposition.get("issue_code"), thread, position))
            db.execute("UPDATE threads SET acknowledged=? WHERE id=?", (committed, thread))
            db.execute("UPDATE owner SET delivery_health='accepted' WHERE singleton=1")
            self._cleanup(db)
            return True

    def _used_bytes(self, db):
        # Bound the ownership catalog as well as raw evidence. SQLite pages,
        # indexes and its fixed schema are additional storage overhead.
        return sum(db.execute(query).fetchone()[0] for query in (
            "SELECT COALESCE(SUM(byte_size),0) FROM events",
            "SELECT COALESCE(SUM(byte_size),0) FROM quarantine",
            "SELECT COALESCE(SUM(length(CAST(id||project||registration AS BLOB))),0) FROM threads",
        ))

    def _cleanup(self, db):
        # Canonical issues remain in Agent Hub; expire acknowledged local rows.
        # Never delete pending observations or unbound quarantine evidence.
        db.execute("UPDATE events SET observation=NULL,byte_size=0 WHERE accepted_at IS NOT NULL AND accepted_at<=?", (time.time() - self.retention_seconds,))
        db.execute("DELETE FROM events WHERE observation IS NULL")

    def status(self) -> dict:
        with self.connect() as db:
            self._cleanup(db)
            count, size = db.execute("SELECT COUNT(*),COALESCE(SUM(byte_size),0) FROM events WHERE accepted_at IS NULL").fetchone()
            quarantine = db.execute("SELECT COUNT(*),COALESCE(SUM(byte_size),0) FROM quarantine").fetchone()
            owner = self.owner()
            return {"health": owner["health"], "delivery_health": owner["delivery_health"], "capture_disabled": bool(owner["capture_disabled"]), "capture_gaps": owner["gaps"], "pending": count, "pending_bytes": size, "quarantined": quarantine[0], "quarantined_bytes": quarantine[1], "used_bytes": self._used_bytes(db), "quota_bytes": self.max_bytes, "raw_retention_seconds": self.retention_seconds, "threads": [{"thread_id": r["id"], "project_id": r["project"], "source_id": r["source_id"], "acknowledged": r["acknowledged"]} for r in self.threads()]}
