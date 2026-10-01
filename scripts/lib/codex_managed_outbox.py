"""Host-local durable transport spool. Agent Hub alone owns receipt checkpoints."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import sqlite3
import stat
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
        directory = path.parent.lstat()
        if not stat.S_ISDIR(directory.st_mode) or directory.st_uid != os.getuid() or stat.S_IMODE(directory.st_mode) != 0o700:
            raise ValueError("Managed outbox requires a private owned directory (0700)")
        self.path = path
        self.max_bytes = max_bytes
        self.retention_seconds = retention_seconds
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            if os.fstat(fd).st_uid != os.getuid():
                raise ValueError("Managed outbox requires an owned database")
            os.fchmod(fd, 0o600)
        finally:
            os.close(fd)
        with self.connect() as db:
            # New databases reclaim deleted pages incrementally. Existing spools
            # are migrated once below without discarding their pending evidence.
            db.execute("PRAGMA auto_vacuum=INCREMENTAL")
            db.execute("BEGIN IMMEDIATE")
            if db.execute("PRAGMA user_version").fetchone()[0] > 2:
                raise ValueError("managed_outbox_schema_unsupported")
            schema = """
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
                    disposition TEXT, issue TEXT, generation INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(thread,generation,position)
                );
                CREATE TABLE IF NOT EXISTS quarantine (
                    id TEXT PRIMARY KEY, payload TEXT NOT NULL, byte_size INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS retired_sources (
                    id TEXT NOT NULL, generation INTEGER NOT NULL, project TEXT NOT NULL,
                    registration TEXT NOT NULL, next_position INTEGER NOT NULL,
                    source_id TEXT, acknowledged INTEGER NOT NULL,
                    PRIMARY KEY(id,generation)
                );
            """
            for statement in schema.split(";"):
                if statement.strip():
                    db.execute(statement)
            for table, additions in {
                "threads": {"generation": "INTEGER NOT NULL DEFAULT 0"},
                "events": {"generation": "INTEGER NOT NULL DEFAULT 0"},
                "quarantine": {"position": "INTEGER", "registration": "TEXT", "source_reference": "TEXT NOT NULL DEFAULT '{}'", "source_id": "TEXT", "accepted_at": "REAL", "disposition": "TEXT", "issue": "TEXT"},
            }.items():
                columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
                for name, declaration in additions.items():
                    if name not in columns:
                        db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")
            primary = [row[1] for row in db.execute("PRAGMA table_info(events)") if row[5]]
            interrupted = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='legacy_events'").fetchone()
            if primary == ["thread", "position"] or interrupted:
                db.execute("""CREATE TABLE events_v2 (
                        thread TEXT NOT NULL REFERENCES threads(id), position INTEGER NOT NULL,
                        observation TEXT, byte_size INTEGER NOT NULL, accepted_at REAL,
                        disposition TEXT, issue TEXT, generation INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY(thread,generation,position)
                    )""")
                for source in (["events", "legacy_events"] if interrupted else ["events"]):
                    columns = {row[1] for row in db.execute(f"PRAGMA table_info({source})")}
                    generation = "generation" if "generation" in columns else "0"
                    conflict = db.execute(f"SELECT 1 FROM {source} AS old JOIN events_v2 AS new ON old.thread=new.thread AND old.position=new.position AND {('old.generation' if 'generation' in columns else '0')}=new.generation WHERE old.observation IS NOT new.observation LIMIT 1").fetchone()
                    if conflict:
                        raise ValueError("Interrupted migration has conflicting original receipts")
                    db.execute(f"INSERT OR IGNORE INTO events_v2 SELECT thread,position,observation,byte_size,accepted_at,disposition,issue,{generation} FROM {source}")
                db.execute("DROP TABLE events")
                if interrupted:
                    db.execute("DROP TABLE legacy_events")
                db.execute("ALTER TABLE events_v2 RENAME TO events")
            db.execute("PRAGMA user_version=2")
            db.execute("INSERT OR IGNORE INTO metadata VALUES('quarantine_next_position','1')")
            db.execute("INSERT OR IGNORE INTO owner(singleton,producer,epoch,health) VALUES(1,?,?,?)", (str(uuid4()), str(uuid4()), "new"))
        with self.connect() as db:
            if db.execute("PRAGMA auto_vacuum").fetchone()[0] != 2:
                db.execute("PRAGMA auto_vacuum=INCREMENTAL")
                db.execute("VACUUM")

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

    def enable_capture(self):
        with self.connect() as db:
            db.execute("UPDATE owner SET capture_disabled=0,health='reenable_pending' WHERE singleton=1")

    def metadata(self, key: str, value: dict | None = None) -> dict:
        with self.connect() as db:
            if value is not None:
                db.execute("INSERT OR REPLACE INTO metadata VALUES(?,?)", (key, json.dumps(value, sort_keys=True)))
                if self._used_bytes(db) > self.max_bytes:
                    raise OutboxFull("Managed metadata exceeds quota")
                return value
            row = db.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else {}

    def quarantine(self, payload: dict, *, registration: dict | None = None, reference: dict | None = None):
        """Retain an unsupported unbound wire frame without inventing a subject."""
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        size = len(encoded.encode()) + len(json.dumps(registration or {}, sort_keys=True).encode()) + len(json.dumps(reference or {}, sort_keys=True).encode())
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._cleanup(db)
            used = self._used_bytes(db)
            if used + size > self.max_bytes:
                raise OutboxFull("Unbound capture exceeds quota")
            key = "quarantine_next_position" if not registration else "quarantine_position:" + hashlib.sha256(json.dumps(registration, sort_keys=True).encode()).hexdigest()
            db.execute("INSERT OR IGNORE INTO metadata VALUES(?, '1')", (key,))
            position = int(db.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()[0])
            db.execute("INSERT INTO quarantine(id,payload,byte_size,position,registration,source_reference) VALUES(?,?,?,?,?,?)", (str(uuid4()), encoded, size, position, json.dumps(registration, sort_keys=True) if registration else None, json.dumps(reference or {}, sort_keys=True)))
            db.execute("UPDATE metadata SET value=? WHERE key=?", (str(position + 1), key))
            if self._used_bytes(db) > self.max_bytes:
                raise OutboxFull("Unbound capture metadata exceeds quota")

    def quarantines(self) -> list[dict]:
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM quarantine WHERE accepted_at IS NULL ORDER BY position,id")]

    def bind_quarantine(self, identifier: str, receipt: dict):
        with self.connect() as db:
            row = db.execute("SELECT * FROM quarantine WHERE id=?", (identifier,)).fetchone()
            if receipt.get("schema_version") != "native-observation.v1" or receipt.get("authenticity") != "collector_attested" or row["source_id"] not in (None, receipt.get("source_id")):
                raise ValueError("Quarantine acknowledgement binding mismatch")
            if not 0 <= receipt.get("committed_position", -1) <= self._quarantine_limit(db, row):
                raise ValueError("Quarantine acknowledgement exceeds captured positions")
            db.execute("UPDATE quarantine SET source_id=? WHERE id=?", (receipt["source_id"], identifier))

    def _quarantine_limit(self, db, row) -> int:
        key = "quarantine_position:" + hashlib.sha256(row["registration"].encode()).hexdigest() if row["registration"] else "quarantine_next_position"
        return int(db.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()[0]) - 1

    def accept_quarantine(self, identifier: str, result: dict) -> bool:
        with self.connect() as db:
            row = db.execute("SELECT * FROM quarantine WHERE id=?", (identifier,)).fetchone()
            dispositions = result.get("dispositions", [])
            if result.get("schema_version") != "native-observation.v1" or result.get("authenticity") != "collector_attested" or result.get("source_id") != row["source_id"] or len(dispositions) != 1 or dispositions[0].get("position") != row["position"]:
                raise ValueError("Quarantine acknowledgement does not name the sent receipt")
            if not 0 <= result.get("committed_position", -1) <= self._quarantine_limit(db, row):
                raise ValueError("Quarantine acknowledgement exceeds captured positions")
            disposition = dispositions[0]
            if disposition.get("disposition") == "conflict":
                db.execute("UPDATE quarantine SET disposition='conflict',issue=? WHERE id=?", (disposition.get("issue_code"), identifier))
                db.execute("UPDATE owner SET delivery_health='receipt_conflict' WHERE singleton=1")
                return False
            if disposition.get("disposition") not in {"quarantined", "replayed", "retained", "accounted", "reconciled", "unresolved", "unsupported", "inherited"} or result.get("committed_position", -1) < row["position"]:
                raise ValueError("Quarantine receipt is not durably acknowledged")
            db.execute("UPDATE quarantine SET accepted_at=?,disposition=?,issue=? WHERE id=?", (time.time(), disposition["disposition"], disposition.get("issue_code"), identifier))
            self._cleanup(db)
            return True

    def rotate_protocol(self, *, version: str, fingerprint: str):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT value FROM metadata WHERE key='protocol'").fetchone()
            if previous:
                profile = json.loads(previous[0])
                if (profile.get("provider_version"), profile.get("schema_fingerprint")) != (version, fingerprint):
                    current = db.execute("SELECT value FROM metadata WHERE key='protocol_generation'").fetchone()
                    generation = json.loads(current[0])["generation"] + 1 if current else 1
                    db.execute("INSERT OR REPLACE INTO metadata VALUES('protocol_generation',?)", (json.dumps({"generation": generation}),))
            for row in db.execute("SELECT * FROM threads").fetchall():
                registration = json.loads(row["registration"])
                if (registration.get("provider_version"), registration.get("schema_fingerprint")) == (version, fingerprint):
                    continue
                db.execute("INSERT INTO retired_sources VALUES(?,?,?,?,?,?,?)", (row["id"], row["generation"], row["project"], row["registration"], row["next_position"], row["source_id"], row["acknowledged"]))
                registration.update(provider_version=version, schema_fingerprint=fingerprint, generation=row["generation"] + 1, predecessor_source_id=row["source_id"])
                db.execute("UPDATE threads SET generation=generation+1,registration=?,source_id=NULL,acknowledged=0,next_position=1 WHERE id=?", (json.dumps(registration, sort_keys=True, separators=(",", ":")), row["id"]))
            if self._used_bytes(db) > self.max_bytes:
                raise OutboxFull("Protocol source registry exceeds quota")

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

    def streams(self) -> list[dict]:
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM retired_sources UNION ALL SELECT id,generation,project,registration,next_position,source_id,acknowledged FROM threads ORDER BY id,generation")]

    def capture(self, thread: str, *, kind: str, payload: dict, reference: dict | None = None) -> int:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._cleanup(db)
            row = db.execute("SELECT next_position,generation FROM threads WHERE id=?", (thread,)).fetchone()
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
            db.execute("INSERT INTO events(thread,position,observation,byte_size,generation) VALUES(?,?,?,?,?)", (thread, position, encoded, size, row["generation"]))
            db.execute("UPDATE threads SET next_position=next_position+1 WHERE id=?", (thread,))
            return position

    def pending(self, thread: str, generation: int | None = None) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT observation FROM events WHERE thread=? AND accepted_at IS NULL AND (? IS NULL OR generation=?) ORDER BY position LIMIT 1", (thread, generation, generation)).fetchone()
            return json.loads(row[0]) if row else None

    def _stream_table(self, db, thread: str, generation: int | None):
        active = db.execute("SELECT generation FROM threads WHERE id=?", (thread,)).fetchone()[0]
        return ("threads", active) if generation in (None, active) else ("retired_sources", generation)

    def predecessor(self, thread: str, generation: int) -> str | None:
        with self.connect() as db:
            row = db.execute("SELECT source_id FROM retired_sources WHERE id=? AND generation=?", (thread, generation - 1)).fetchone()
            return row[0] if row else None

    def bind_source(self, thread: str, receipt: dict, generation: int | None = None):
        with self.connect() as db:
            table, generation = self._stream_table(db, thread, generation)
            row = db.execute(f"SELECT source_id,next_position,acknowledged FROM {table} WHERE id=? AND generation=?", (thread, generation)).fetchone()
            if receipt.get("schema_version") != "native-observation.v1" or receipt.get("authenticity") != "collector_attested":
                raise ValueError("Unexpected Agent Hub source acknowledgement")
            if row["source_id"] not in (None, receipt["source_id"]):
                raise ValueError("Agent Hub source identity changed")
            # Registration cannot acknowledge pending local payloads. Only their
            # exact accepted/replayed dispositions permit outbox cleanup.
            if not 0 <= receipt["committed_position"] < row["next_position"]:
                raise ValueError("Agent Hub returned an impossible source position")
            db.execute(f"UPDATE {table} SET source_id=? WHERE id=? AND generation=?", (receipt["source_id"], thread, generation))

    def accept(self, thread: str, position: int, result: dict, generation: int | None = None) -> bool:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            table, generation = self._stream_table(db, thread, generation)
            row = db.execute(f"SELECT * FROM {table} WHERE id=? AND generation=?", (thread, generation)).fetchone()
            if result.get("schema_version") != "native-observation.v1" or result.get("source_id") != row["source_id"] or result.get("authenticity") != "collector_attested":
                raise ValueError("Agent Hub acknowledgement binding mismatch")
            committed = result["committed_position"]
            if not 0 <= committed < row["next_position"]:
                raise ValueError("Agent Hub acknowledgement exceeds captured positions")
            dispositions = result.get("dispositions", [])
            if len(dispositions) != 1 or dispositions[0]["position"] != position:
                raise ValueError("Agent Hub acknowledgement does not name the sent receipt")
            disposition = dispositions[0]
            if not db.execute("SELECT 1 FROM events WHERE thread=? AND generation=? AND position=?", (thread, generation, position)).fetchone():
                raise ValueError("Agent Hub acknowledgement names no local receipt")
            if disposition["disposition"] == "conflict":
                db.execute("UPDATE events SET disposition=?,issue=? WHERE thread=? AND position=? AND generation=?", ("conflict", disposition.get("issue_code"), thread, position, generation))
                db.execute("UPDATE owner SET delivery_health='receipt_conflict' WHERE singleton=1")
                return False
            if disposition["disposition"] not in {"replayed", "retained", "accounted", "reconciled", "unresolved", "unsupported", "inherited"}:
                raise ValueError("Unknown Agent Hub disposition")
            if committed < position or committed < row["acknowledged"]:
                db.execute("UPDATE owner SET delivery_health='acknowledgement_gap' WHERE singleton=1")
                return False
            db.execute("UPDATE events SET accepted_at=?,disposition=?,issue=? WHERE thread=? AND position=? AND generation=?", (time.time(), disposition["disposition"], disposition.get("issue_code"), thread, position, generation))
            db.execute(f"UPDATE {table} SET acknowledged=? WHERE id=? AND generation=?", (max(row["acknowledged"], position), thread, generation))
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
            "SELECT COALESCE(SUM(length(CAST(id||project||registration AS BLOB))),0) FROM retired_sources",
            "SELECT COALESCE(SUM(length(CAST(key||value AS BLOB))),0) FROM metadata",
        ))

    def _cleanup(self, db):
        # Canonical issues remain in Agent Hub; expire acknowledged local rows.
        # Never delete pending observations or unbound quarantine evidence.
        db.execute("UPDATE events SET observation=NULL,byte_size=0 WHERE accepted_at IS NOT NULL AND accepted_at<=?", (time.time() - self.retention_seconds,))
        db.execute("DELETE FROM events WHERE observation IS NULL")
        db.execute("DELETE FROM quarantine WHERE accepted_at IS NOT NULL AND accepted_at<=?", (time.time() - self.retention_seconds,))
        db.execute("""DELETE FROM retired_sources AS old WHERE generation>0
            AND NOT EXISTS (SELECT 1 FROM events WHERE thread=old.id AND generation=old.generation)
            AND (EXISTS (SELECT 1 FROM retired_sources AS successor WHERE successor.id=old.id AND successor.generation=old.generation+1 AND successor.source_id IS NOT NULL)
                OR EXISTS (SELECT 1 FROM threads AS successor WHERE successor.id=old.id AND successor.generation=old.generation+1 AND successor.source_id IS NOT NULL))""")

    def reclaim(self):
        with self.connect() as db:
            self._cleanup(db)
        with self.connect() as db:
            db.execute("PRAGMA incremental_vacuum").fetchall()

    def status(self) -> dict:
        self.reclaim()
        with self.connect() as db:
            self._cleanup(db)
            count, size = db.execute("SELECT COUNT(*),COALESCE(SUM(byte_size),0) FROM events WHERE accepted_at IS NULL").fetchone()
            quarantine = db.execute("SELECT COUNT(*),COALESCE(SUM(byte_size),0) FROM quarantine WHERE accepted_at IS NULL").fetchone()
            owner = self.owner()
            conflicts = db.execute("SELECT COUNT(*) FROM events WHERE accepted_at IS NULL AND disposition='conflict'").fetchone()[0] + db.execute("SELECT COUNT(*) FROM quarantine WHERE accepted_at IS NULL AND disposition='conflict'").fetchone()[0]
            if conflicts:
                owner["delivery_health"] = "receipt_conflict"
            try:
                with self.lease():
                    process_active = False
            except BlockingIOError:
                process_active = True
            threads = []
            for row in self.threads():
                registration = json.loads(row["registration"])
                threads.append({"thread_id": row["id"], "project_id": row["project"], "source_id": row["source_id"], "acknowledged": row["acknowledged"], "provider_version": registration.get("provider_version"), "schema_fingerprint": registration.get("schema_fingerprint"), "generation": row["generation"]})
            return {"health": owner["health"], "delivery_health": owner["delivery_health"], "capture_disabled": bool(owner["capture_disabled"]), "capture_gaps": owner["gaps"], "pending": count, "pending_bytes": size, "quarantined": quarantine[0], "quarantined_bytes": quarantine[1], "conflicts": conflicts, "used_bytes": self._used_bytes(db), "quota_bytes": self.max_bytes, "raw_retention_seconds": self.retention_seconds, "physical_bytes": self.path.stat().st_size, "process_active": process_active, "threads": threads, **self.metadata("protocol")}
