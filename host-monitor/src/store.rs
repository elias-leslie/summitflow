use flate2::{Compression, write::GzEncoder};
use rusqlite::{Connection, OptionalExtension, params};
use serde_json::{Value, json};
use std::{
    fs,
    os::unix::fs::PermissionsExt,
    path::{Path, PathBuf},
};

const MINUTE_NS: i64 = 60_000_000_000;
const RAW_AGE_NS: i64 = 48 * 60 * MINUTE_NS;
const ROLLUP_AGE_NS: i64 = 14 * 24 * 60 * MINUTE_NS;
const MAX_BYTES: u64 = 512 * 1024 * 1024;
const MIN_FREE_BYTES: u64 = 1024 * 1024 * 1024;
const DETAIL_RESERVE_BYTES: i64 = 192 * 1024 * 1024;
const BASELINE_RESERVE_BYTES: i64 = 256 * 1024 * 1024;
const RECENT_BASELINE_NS: i64 = 60 * MINUTE_NS;

pub struct Sample<'a> {
    pub at_ns: i64,
    pub mono_ns: i64,
    pub boot_id: &'a str,
    pub mode: &'a str,
    pub host: &'a Value,
    pub services: &'a Value,
    pub processes: &'a [Value],
    pub seen: u64,
    pub denied: u64,
    pub exited: u64,
    pub errors: &'a [Value],
    pub duration_ns: u64,
    pub reason: Option<&'a str>,
}

pub struct Store {
    pub conn: Connection,
    pub path: PathBuf,
    detail_bytes: i64,
    pending_bucket: Option<i64>,
    pending_count: u8,
}

fn sqlite_error(message: &str) -> rusqlite::Error {
    rusqlite::Error::InvalidParameterName(message.to_owned())
}

impl Store {
    pub fn open(state: &Path, host_id: &str, boot_id: &str) -> rusqlite::Result<Self> {
        fs::create_dir_all(state).map_err(|e| sqlite_error(&e.to_string()))?;
        fs::set_permissions(state, fs::Permissions::from_mode(0o700))
            .map_err(|e| sqlite_error(&e.to_string()))?;
        let path = state.join("monitor.sqlite3");
        let first = !path.exists();
        let conn = Connection::open(&path)?;
        for suffix in ["", "-wal", "-shm"] {
            let p = PathBuf::from(format!("{}{}", path.display(), suffix));
            if p.exists() {
                fs::set_permissions(p, fs::Permissions::from_mode(0o600))
                    .map_err(|e| sqlite_error(&e.to_string()))?;
            }
        }
        if first {
            conn.pragma_update(None, "page_size", 1024)?;
            conn.pragma_update(None, "auto_vacuum", "INCREMENTAL")?;
            conn.execute_batch("VACUUM")?;
        }
        conn.pragma_update(None, "journal_mode", "WAL")?;
        conn.pragma_update(None, "synchronous", "FULL")?;
        conn.pragma_update(None, "busy_timeout", 1000)?;
        conn.execute_batch(
            "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);",
        )?;
        let version: Option<String> = conn
            .query_row(
                "SELECT value FROM meta WHERE key='schema_version'",
                [],
                |r| r.get(0),
            )
            .optional()?;
        if (version.is_none() && !first) || version.as_deref().is_some_and(|v| v != "1") {
            return Err(sqlite_error("unsupported schema version"));
        }
        conn.execute_batch("\
            CREATE TABLE IF NOT EXISTS samples(id INTEGER PRIMARY KEY,sampled_at_ns INTEGER NOT NULL,monotonic_ns INTEGER NOT NULL,boot_id TEXT NOT NULL,mode TEXT NOT NULL,host_json TEXT NOT NULL,services_json TEXT NOT NULL,process_blob BLOB NOT NULL,processes_seen INTEGER NOT NULL,processes_permission_denied INTEGER NOT NULL,processes_exited INTEGER NOT NULL,errors_json TEXT NOT NULL,duration_ns INTEGER NOT NULL,capture_reason TEXT);\
            CREATE INDEX IF NOT EXISTS samples_time_idx ON samples(sampled_at_ns,id);\
            CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,sampled_at_ns INTEGER NOT NULL,kind TEXT NOT NULL,severity TEXT NOT NULL,entity TEXT,details_json TEXT NOT NULL);\
            CREATE INDEX IF NOT EXISTS events_time_idx ON events(sampled_at_ns,id);\
            CREATE TABLE IF NOT EXISTS host_rollups(bucket_start_ns INTEGER PRIMARY KEY,sample_count INTEGER NOT NULL,values_json TEXT NOT NULL,coverage_json TEXT NOT NULL);")?;
        for (key, value) in [
            ("schema_version", "1"),
            ("host_id", host_id),
            ("boot_id", boot_id),
            ("collector_version", env!("CARGO_PKG_VERSION")),
        ] {
            conn.execute("INSERT INTO meta(key,value) VALUES(?1,?2) ON CONFLICT(key) DO UPDATE SET value=excluded.value", params![key,value])?;
        }
        for suffix in ["-wal", "-shm"] {
            let p = PathBuf::from(format!("{}{}", path.display(), suffix));
            if p.exists() {
                fs::set_permissions(p, fs::Permissions::from_mode(0o600))
                    .map_err(|e| sqlite_error(&e.to_string()))?;
            }
        }
        let detail_bytes = conn.query_row(
            "SELECT COALESCE(SUM(length(process_blob)),0) FROM samples WHERE mode='detail'",
            [],
            |r| r.get(0),
        )?;
        let latest_bucket: Option<i64> = conn
            .query_row(
                "SELECT sampled_at_ns FROM samples WHERE mode='baseline' ORDER BY id DESC LIMIT 1",
                [],
                |r| r.get::<_, i64>(0),
            )
            .optional()?
            .map(|at| at.div_euclid(MINUTE_NS) * MINUTE_NS);
        let mut store = Self {
            conn,
            path,
            detail_bytes,
            pending_bucket: None,
            pending_count: 0,
        };
        if let Some(bucket) = latest_bucket {
            store.flush_bucket(bucket)?;
        }
        Ok(store)
    }

    pub fn write(&mut self, s: &Sample<'_>) -> rusqlite::Result<()> {
        let mut enc = GzEncoder::new(Vec::new(), Compression::fast());
        serde_json::to_writer(&mut enc, s.processes).map_err(|e| sqlite_error(&e.to_string()))?;
        let blob = enc.finish().map_err(|e| sqlite_error(&e.to_string()))?;
        if s.mode == "detail" {
            self.evict_detail_for(blob.len() as i64, s.at_ns)?;
            if self.detail_bytes.saturating_add(blob.len() as i64) > DETAIL_RESERVE_BYTES
                || self.bytes() > MAX_BYTES.saturating_sub(64 * 1024 * 1024)
                || self.free_bytes() < MIN_FREE_BYTES
            {
                return Err(sqlite_error("detail skipped: storage headroom"));
            }
        } else if self.bytes() >= MAX_BYTES || self.free_bytes() < MIN_FREE_BYTES {
            self.prune(s.at_ns)?;
            if self.bytes() >= MAX_BYTES || self.free_bytes() < MIN_FREE_BYTES {
                return Err(sqlite_error("baseline skipped: storage headroom"));
            }
        }
        let tx = self.conn.transaction()?;
        tx.execute("INSERT INTO samples(sampled_at_ns,monotonic_ns,boot_id,mode,host_json,services_json,process_blob,processes_seen,processes_permission_denied,processes_exited,errors_json,duration_ns,capture_reason) VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13)", params![s.at_ns,s.mono_ns,s.boot_id,s.mode,s.host.to_string(),s.services.to_string(),&blob,s.seen,s.denied,s.exited,Value::Array(s.errors.to_vec()).to_string(),s.duration_ns,s.reason])?;
        let next_rollup = if s.mode == "baseline" {
            let bucket = s.at_ns.div_euclid(MINUTE_NS) * MINUTE_NS;
            let changed = self.pending_bucket.is_some_and(|b| b != bucket);
            if changed && self.pending_count > 0 {
                rebuild_rollup(&tx, self.pending_bucket.unwrap())?;
            }
            let mut next_count = if changed || self.pending_bucket.is_none() {
                1
            } else {
                self.pending_count.saturating_add(1)
            };
            if next_count >= 3 {
                rebuild_rollup(&tx, bucket)?;
                next_count = 0;
            }
            Some((bucket, next_count))
        } else {
            None
        };
        tx.commit()?;
        if let Some((bucket, count)) = next_rollup {
            self.pending_bucket = Some(bucket);
            self.pending_count = count;
        }
        if s.mode == "detail" {
            self.detail_bytes += blob.len() as i64;
        }
        Ok(())
    }

    fn flush_bucket(&mut self, bucket: i64) -> rusqlite::Result<()> {
        let tx = self.conn.transaction()?;
        rebuild_rollup(&tx, bucket)?;
        tx.commit()?;
        Ok(())
    }
    pub fn flush_rollups(&mut self) -> rusqlite::Result<()> {
        if self.pending_count > 0 {
            self.flush_bucket(self.pending_bucket.unwrap())?;
            self.pending_count = 0;
        }
        Ok(())
    }

    fn evict_detail_for(&mut self, incoming: i64, at: i64) -> rusqlite::Result<()> {
        self.evict_detail_to(incoming, at, DETAIL_RESERVE_BYTES)
    }
    fn evict_detail_to(&mut self, incoming: i64, at: i64, quota: i64) -> rusqlite::Result<()> {
        let mut evicted = 0;
        while self.detail_bytes.saturating_add(incoming) > quota {
            let n=self.conn.execute("DELETE FROM samples WHERE id IN (SELECT id FROM samples WHERE mode='detail' ORDER BY sampled_at_ns,id LIMIT 100)",[])?;
            if n == 0 {
                break;
            }
            evicted += n;
            self.detail_bytes = self.conn.query_row(
                "SELECT COALESCE(SUM(length(process_blob)),0) FROM samples WHERE mode='detail'",
                [],
                |r| r.get(0),
            )?;
        }
        if evicted > 0 {
            self.event(
                at,
                "retention_gap",
                "warning",
                None,
                &json!({"detail_samples_evicted":evicted,"reason":"detail_quota"}),
            )?;
        }
        Ok(())
    }

    pub fn event(
        &self,
        at: i64,
        kind: &str,
        severity: &str,
        entity: Option<&str>,
        details: &Value,
    ) -> rusqlite::Result<()> {
        self.event_with_limits(
            at,
            kind,
            severity,
            entity,
            details,
            MAX_BYTES.saturating_sub(64 * 1024 * 1024),
            MIN_FREE_BYTES,
        )
    }

    fn event_with_limits(
        &self,
        at: i64,
        kind: &str,
        severity: &str,
        entity: Option<&str>,
        details: &Value,
        max_bytes: u64,
        min_free: u64,
    ) -> rusqlite::Result<()> {
        // Reserve room for baseline samples and the WAL. Events must not consume
        // the last available disk space when the writer is already under pressure.
        if self.bytes() >= max_bytes || self.free_bytes() < min_free {
            return Err(sqlite_error("event skipped: storage headroom"));
        }
        let mut bounded = details.to_string();
        if bounded.len() > 2048 {
            bounded = json!({"truncated":true}).to_string();
        }
        let bounded_entity = entity.map(|s| s.chars().take(256).collect::<String>());
        self.conn.execute("INSERT INTO events(sampled_at_ns,kind,severity,entity,details_json) VALUES(?1,?2,?3,?4,?5)",params![at,kind,severity,bounded_entity,bounded])?;
        Ok(())
    }

    pub fn prune(&mut self, now_ns: i64) -> rusqlite::Result<()> {
        self.prune_to(now_ns, MAX_BYTES, MIN_FREE_BYTES)
    }
    fn prune_to(&mut self, now_ns: i64, max_bytes: u64, min_free: u64) -> rusqlite::Result<()> {
        let tx = self.conn.transaction()?;
        let aged = tx.execute(
            "DELETE FROM samples WHERE sampled_at_ns < ?1",
            [now_ns - RAW_AGE_NS],
        )?;
        tx.execute(
            "DELETE FROM host_rollups WHERE bucket_start_ns < ?1",
            [now_ns - ROLLUP_AGE_NS],
        )?;
        tx.execute(
            "DELETE FROM events WHERE sampled_at_ns < ?1",
            [now_ns - ROLLUP_AGE_NS],
        )?;
        tx.commit()?;
        self.detail_bytes = self.conn.query_row(
            "SELECT COALESCE(SUM(length(process_blob)),0) FROM samples WHERE mode='detail'",
            [],
            |r| r.get(0),
        )?;
        let mut detail_evicted = 0;
        let mut baseline_evicted = 0;
        for _ in 0..100 {
            let baseline_bytes:i64=self.conn.query_row("SELECT COALESCE(SUM(length(host_json)+length(services_json)+length(process_blob)+length(errors_json)),0) FROM samples WHERE mode='baseline'",[],|r|r.get(0))?;
            let over_total = self.bytes() > max_bytes.saturating_sub(64 * 1024 * 1024)
                || self.free_bytes() < min_free;
            if !over_total && baseline_bytes <= BASELINE_RESERVE_BYTES {
                break;
            }
            let n = self.conn.execute("DELETE FROM samples WHERE id IN (SELECT id FROM samples WHERE mode='detail' ORDER BY sampled_at_ns,id LIMIT 100)", [])?;
            if n > 0 {
                detail_evicted += n;
                self.detail_bytes = self.conn.query_row(
                    "SELECT COALESCE(SUM(length(process_blob)),0) FROM samples WHERE mode='detail'",
                    [],
                    |r| r.get(0),
                )?;
            } else {
                let n=self.conn.execute("DELETE FROM samples WHERE id IN (SELECT id FROM samples WHERE mode='baseline' AND sampled_at_ns < ?1 ORDER BY sampled_at_ns,id LIMIT 100)",[now_ns-RECENT_BASELINE_NS])?;
                if n == 0 {
                    break;
                }
                baseline_evicted += n;
            }
            self.conn.execute_batch("PRAGMA incremental_vacuum(500)")?;
            let _ = self.conn.execute_batch("PRAGMA wal_checkpoint(TRUNCATE)");
        }
        if aged > 0 || detail_evicted > 0 || baseline_evicted > 0 {
            let _ = self.event(
                now_ns,
                "retention_gap",
                "warning",
                None,
                &json!({"age_samples_evicted":aged,"detail_samples_evicted":detail_evicted,"baseline_samples_evicted":baseline_evicted}),
            );
        }
        if aged > 0 || detail_evicted > 0 || baseline_evicted > 0 {
            self.conn.execute_batch("PRAGMA incremental_vacuum(100)")?;
            let _ = self.conn.execute_batch("PRAGMA wal_checkpoint(PASSIVE)");
        }
        let wal_bytes = fs::metadata(format!("{}-wal", self.path.display()))
            .map(|m| m.len())
            .unwrap_or(0);
        if wal_bytes > 32 * 1024 * 1024 {
            let _ = self.conn.execute_batch("PRAGMA wal_checkpoint(TRUNCATE)");
        }
        Ok(())
    }

    pub fn bytes(&self) -> u64 {
        ["", "-wal", "-shm"]
            .iter()
            .map(|s| {
                fs::metadata(format!("{}{}", self.path.display(), s))
                    .map(|m| m.len())
                    .unwrap_or(0)
            })
            .sum()
    }
    fn free_bytes(&self) -> u64 {
        let Ok(path) = std::ffi::CString::new(self.path.to_string_lossy().as_bytes()) else {
            return 0;
        };
        let mut stat = std::mem::MaybeUninit::<libc::statvfs>::uninit();
        if unsafe { libc::statvfs(path.as_ptr(), stat.as_mut_ptr()) } != 0 {
            return 0;
        }
        let stat = unsafe { stat.assume_init() };
        stat.f_bavail.saturating_mul(stat.f_frsize)
    }
}

fn rebuild_rollup(tx: &rusqlite::Transaction<'_>, bucket: i64) -> rusqlite::Result<()> {
    let mut values = json!({});
    let mut coverage = json!({"gap_count":0});
    let mut count = 0i64;
    let mut previous: Option<(String, i64)> = None;
    {
        let mut stmt=tx.prepare("SELECT host_json,boot_id,monotonic_ns FROM samples WHERE mode='baseline' AND sampled_at_ns>=?1 AND sampled_at_ns<?2 ORDER BY sampled_at_ns,id")?;
        let mut rows = stmt.query(params![bucket, bucket + MINUTE_NS])?;
        while let Some(row) = rows.next()? {
            let host_text: String = row.get(0)?;
            let boot: String = row.get(1)?;
            let mono: i64 = row.get(2)?;
            let host: Value =
                serde_json::from_str(&host_text).map_err(|e| sqlite_error(&e.to_string()))?;
            let fields = host
                .as_object()
                .ok_or_else(|| sqlite_error("host is not object"))?;
            let values_obj = values.as_object_mut().unwrap();
            let coverage_obj = coverage.as_object_mut().unwrap();
            for (key, raw) in fields {
                if matches!(
                    key.as_str(),
                    "leaders_sampled_at_ns"
                        | "process_scan_observed_at_ns"
                        | "process_scan_observed_monotonic_ns"
                ) {
                    continue;
                }
                let item = values_obj.entry(key).or_insert_with(
                    || json!({"min":null,"max":null,"mean":null,"last":null,"valid_count":0}),
                );
                if let Some(number) = raw.as_f64().filter(|v| v.is_finite()) {
                    let n = item["valid_count"].as_u64().unwrap_or(0);
                    let mean = item["mean"].as_f64().unwrap_or(0.0);
                    item["min"] = json!(item["min"].as_f64().map_or(number, |v| v.min(number)));
                    item["max"] = json!(item["max"].as_f64().map_or(number, |v| v.max(number)));
                    item["mean"] = json!((mean * n as f64 + number) / (n + 1) as f64);
                    item["last"] = raw.clone();
                    item["valid_count"] = json!(n + 1);
                } else {
                    let key = format!("{key}_unavailable_count");
                    let n = coverage_obj.get(&key).and_then(Value::as_u64).unwrap_or(0);
                    coverage_obj.insert(key, json!(n + 1));
                }
            }
            if previous.as_ref().is_some_and(|(prev_boot, prev_mono)| {
                prev_boot != &boot || mono <= *prev_mono || mono - *prev_mono > 10_000_000_000
            }) {
                let obj = coverage.as_object_mut().unwrap();
                let n = obj.get("gap_count").and_then(Value::as_u64).unwrap_or(0);
                obj.insert("gap_count".into(), json!(n + 1));
            }
            previous = Some((boot, mono));
            count += 1;
        }
    }
    if count == 0 {
        tx.execute(
            "DELETE FROM host_rollups WHERE bucket_start_ns=?1",
            [bucket],
        )?;
    } else {
        tx.execute("INSERT INTO host_rollups(bucket_start_ns,sample_count,values_json,coverage_json) VALUES(?1,?2,?3,?4) ON CONFLICT(bucket_start_ns) DO UPDATE SET sample_count=excluded.sample_count,values_json=excluded.values_json,coverage_json=excluded.coverage_json",params![bucket,count,values.to_string(),coverage.to_string()])?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use flate2::read::GzDecoder;
    use rusqlite::OpenFlags;
    use std::io::Read;

    fn sample<'a>(at: i64, mode: &'a str, host: &'a Value, rows: &'a [Value]) -> Sample<'a> {
        Sample {
            at_ns: at,
            mono_ns: at,
            boot_id: "boot-a",
            mode,
            host,
            services: &Value::Null,
            processes: rows,
            seen: rows.len() as u64,
            denied: 0,
            exited: 0,
            errors: &[],
            duration_ns: 12,
            reason: None,
        }
    }
    #[test]
    fn exact_schema_and_readonly_gzip_history() {
        let dir = tempfile::tempdir().unwrap();
        let mut db = Store::open(dir.path(), "host", "boot-a").unwrap();
        let host = json!({"cpu_busy_pct":23.0,"memory_available_bytes":null});
        let rows = [
            json!({"pid":7,"start_ticks":21,"name":"unit","cpu_user_ns":10,"cpu_system_ns":0,"rss_bytes":4096,"read_bytes":0,"write_bytes":0,"leader_reasons":["rss"]}),
        ];
        db.write(&sample(60_000_000_000, "baseline", &host, &rows))
            .unwrap();
        db.flush_rollups().unwrap();
        drop(db);
        let read = Connection::open_with_flags(
            dir.path().join("monitor.sqlite3"),
            OpenFlags::SQLITE_OPEN_READ_ONLY,
        )
        .unwrap();
        assert_eq!(
            read.query_row("PRAGMA page_size", [], |r| r.get::<_, i64>(0))
                .unwrap(),
            1024
        );
        let cols = read
            .prepare("PRAGMA table_info(samples)")
            .unwrap()
            .query_map([], |r| r.get::<_, String>(1))
            .unwrap()
            .map(Result::unwrap)
            .collect::<Vec<_>>();
        assert_eq!(
            cols,
            [
                "id",
                "sampled_at_ns",
                "monotonic_ns",
                "boot_id",
                "mode",
                "host_json",
                "services_json",
                "process_blob",
                "processes_seen",
                "processes_permission_denied",
                "processes_exited",
                "errors_json",
                "duration_ns",
                "capture_reason"
            ]
        );
        let blob: Vec<u8> = read
            .query_row("SELECT process_blob FROM samples", [], |r| r.get(0))
            .unwrap();
        let mut content = String::new();
        GzDecoder::new(&blob[..])
            .read_to_string(&mut content)
            .unwrap();
        assert_eq!(
            serde_json::from_str::<Value>(&content).unwrap(),
            json!(rows)
        );
        let (n, values, coverage): (i64, String, String) = read
            .query_row(
                "SELECT sample_count,values_json,coverage_json FROM host_rollups",
                [],
                |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
            )
            .unwrap();
        assert_eq!(n, 1);
        assert_eq!(
            serde_json::from_str::<Value>(&values).unwrap()["cpu_busy_pct"]["valid_count"],
            1
        );
        assert_eq!(
            serde_json::from_str::<Value>(&coverage).unwrap()["memory_available_bytes_unavailable_count"],
            1
        );
        assert_eq!(
            fs::metadata(dir.path()).unwrap().permissions().mode() & 0o777,
            0o700
        );
        assert_eq!(
            fs::metadata(dir.path().join("monitor.sqlite3"))
                .unwrap()
                .permissions()
                .mode()
                & 0o777,
            0o600
        );
    }
    #[test]
    fn retention_preserves_recent_baseline_and_rejects_version_mismatch() {
        let dir = tempfile::tempdir().unwrap();
        let mut db = Store::open(dir.path(), "h", "b").unwrap();
        let host = json!({"cpu_busy_pct":null});
        db.write(&sample(1, "baseline", &host, &[])).unwrap();
        let recent = RAW_AGE_NS - MINUTE_NS;
        db.write(&sample(recent, "baseline", &host, &[])).unwrap();
        db.prune(recent).unwrap();
        assert_eq!(
            db.conn
                .query_row("SELECT count(*) FROM samples", [], |r| r.get::<_, i64>(0))
                .unwrap(),
            2
        );
        db.prune(recent + RAW_AGE_NS).unwrap();
        assert_eq!(
            db.conn
                .query_row("SELECT count(*) FROM samples", [], |r| r.get::<_, i64>(0))
                .unwrap(),
            1
        );
        db.conn
            .execute("UPDATE meta SET value='99' WHERE key='schema_version'", [])
            .unwrap();
        drop(db);
        assert!(Store::open(dir.path(), "h", "b").is_err());
    }
    #[test]
    fn write_failure_keeps_prior_commit_readable() {
        let dir = tempfile::tempdir().unwrap();
        let mut db = Store::open(dir.path(), "h", "b").unwrap();
        let host = json!({"cpu_busy_pct":5});
        db.write(&sample(1, "baseline", &host, &[])).unwrap();
        db.conn.execute_batch("CREATE TRIGGER fail_insert BEFORE INSERT ON samples BEGIN SELECT RAISE(FAIL,'disk_full_fixture'); END;").unwrap();
        assert!(db.write(&sample(2, "baseline", &host, &[])).is_err());
        let read = Connection::open_with_flags(&db.path, OpenFlags::SQLITE_OPEN_READ_ONLY).unwrap();
        assert_eq!(
            read.query_row("SELECT count(*) FROM samples", [], |r| r.get::<_, i64>(0))
                .unwrap(),
            1
        );
    }
    #[test]
    fn event_headroom_rejection_keeps_existing_history_readable() {
        let dir = tempfile::tempdir().unwrap();
        let mut db = Store::open(dir.path(), "h", "b").unwrap();
        let host = json!({"cpu_busy_pct":5});
        db.write(&sample(1, "baseline", &host, &[])).unwrap();
        db.event(
            1,
            "service_change",
            "info",
            Some("unit"),
            &json!({"to":"active"}),
        )
        .unwrap();
        assert!(
            db.event_with_limits(2, "pressure", "warning", None, &json!({}), db.bytes(), 0)
                .unwrap_err()
                .to_string()
                .contains("storage headroom")
        );
        assert!(
            db.event_with_limits(
                2,
                "pressure",
                "warning",
                None,
                &json!({}),
                u64::MAX,
                u64::MAX
            )
            .is_err()
        );
        assert_eq!(
            db.conn
                .query_row("SELECT count(*) FROM events", [], |r| r.get::<_, i64>(0))
                .unwrap(),
            1
        );
        db.write(&sample(2, "baseline", &host, &[])).unwrap();
        assert_eq!(
            db.conn
                .query_row(
                    "SELECT count(*) FROM samples WHERE mode='baseline'",
                    [],
                    |r| r.get::<_, i64>(0)
                )
                .unwrap(),
            2
        );
    }
    #[test]
    fn quota_evicts_old_detail_before_recent_baseline() {
        let dir = tempfile::tempdir().unwrap();
        let mut db = Store::open(dir.path(), "h", "b").unwrap();
        let host = json!({"cpu_busy_pct":5});
        let rows = [json!({"pid":4})];
        db.write(&sample(1, "detail", &host, &rows)).unwrap();
        db.write(&sample(2, "baseline", &host, &rows)).unwrap();
        db.evict_detail_to(1, 3, 0).unwrap();
        assert_eq!(
            db.conn
                .query_row(
                    "SELECT count(*) FROM samples WHERE mode='detail'",
                    [],
                    |r| r.get::<_, i64>(0)
                )
                .unwrap(),
            0
        );
        assert_eq!(
            db.conn
                .query_row(
                    "SELECT count(*) FROM samples WHERE mode='baseline'",
                    [],
                    |r| r.get::<_, i64>(0)
                )
                .unwrap(),
            1
        );
        let aged = 3 * 60 * MINUTE_NS;
        db.write(&sample(aged, "baseline", &host, &rows)).unwrap();
        db.prune_to(aged, 0, 0).unwrap();
        assert_eq!(
            db.conn
                .query_row(
                    "SELECT count(*) FROM samples WHERE mode='baseline'",
                    [],
                    |r| r.get::<_, i64>(0)
                )
                .unwrap(),
            1
        );
        assert_eq!(
            db.conn
                .query_row("SELECT min(sampled_at_ns) FROM samples", [], |r| r
                    .get::<_, i64>(0))
                .unwrap(),
            aged
        );
        assert!(
            db.conn
                .query_row(
                    "SELECT count(*) FROM events WHERE kind='retention_gap'",
                    [],
                    |r| r.get::<_, i64>(0)
                )
                .unwrap()
                > 0
        );
    }
    #[test]
    fn sustained_detail_eviction_preserves_baseline_cadence_and_rollup() {
        let dir = tempfile::tempdir().unwrap();
        let mut db = Store::open(dir.path(), "h", "b").unwrap();
        let start = 60 * MINUTE_NS;
        for i in 0..9i64 {
            let at = start + i * 5_000_000_000;
            let host = json!({"cpu_busy_pct":i});
            let services = json!({"backend":{"active_state":"active"}});
            let leaders = [json!({"pid":1,"leader_reasons":["rss"]})];
            let all = [json!({"pid":1}), json!({"pid":2})];
            let baseline = Sample {
                at_ns: at,
                mono_ns: at,
                boot_id: "b",
                mode: "baseline",
                host: &host,
                services: &services,
                processes: &leaders,
                seen: 2,
                denied: 0,
                exited: 0,
                errors: &[],
                duration_ns: 1,
                reason: None,
            };
            let detail = Sample {
                at_ns: at,
                mono_ns: at,
                boot_id: "b",
                mode: "detail",
                host: &host,
                services: &services,
                processes: &all,
                seen: 2,
                denied: 0,
                exited: 0,
                errors: &[],
                duration_ns: 1,
                reason: Some("lease"),
            };
            db.write(&baseline).unwrap();
            db.write(&detail).unwrap();
        }
        db.flush_rollups().unwrap();
        let rollup: (i64, String) = db
            .conn
            .query_row(
                "SELECT sample_count,values_json FROM host_rollups",
                [],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .unwrap();
        assert_eq!(rollup.0, 9);
        assert_eq!(
            serde_json::from_str::<Value>(&rollup.1).unwrap()["cpu_busy_pct"]["max"],
            8.0
        );
        let baseline_times = db
            .conn
            .prepare(
                "SELECT sampled_at_ns FROM samples WHERE mode='baseline' ORDER BY sampled_at_ns",
            )
            .unwrap()
            .query_map([], |r| r.get::<_, i64>(0))
            .unwrap()
            .map(Result::unwrap)
            .collect::<Vec<_>>();
        assert_eq!(
            baseline_times,
            (0..9)
                .map(|i| start + i * 5_000_000_000)
                .collect::<Vec<_>>()
        );
        assert_eq!(
            db.conn
                .query_row(
                    "SELECT count(*) FROM samples WHERE mode='detail'",
                    [],
                    |r| r.get::<_, i64>(0)
                )
                .unwrap(),
            9
        );
        db.evict_detail_to(1, start + 45_000_000_000, 0).unwrap();
        assert_eq!(
            db.conn
                .query_row(
                    "SELECT count(*) FROM samples WHERE mode='detail'",
                    [],
                    |r| r.get::<_, i64>(0)
                )
                .unwrap(),
            0
        );
        assert_eq!(db.conn.query_row("SELECT count(*) FROM samples WHERE mode='baseline' AND json_extract(services_json,'$.backend.active_state')='active'",[],|r|r.get::<_,i64>(0)).unwrap(),9);
        assert_eq!(
            db.conn
                .query_row("SELECT sample_count FROM host_rollups", [], |r| r
                    .get::<_, i64>(0))
                .unwrap(),
            9
        );
    }
    #[test]
    fn rollup_batches_and_restart_backfills_partial_bucket() {
        let dir = tempfile::tempdir().unwrap();
        let mut db = Store::open(dir.path(), "h", "b").unwrap();
        let base = 60 * MINUTE_NS;
        db.write(&sample(base, "baseline", &json!({"cpu_busy_pct":10}), &[]))
            .unwrap();
        db.write(&sample(
            base + 5_000_000_000,
            "baseline",
            &json!({"cpu_busy_pct":null}),
            &[],
        ))
        .unwrap();
        assert_eq!(
            db.conn
                .query_row("SELECT count(*) FROM host_rollups", [], |r| r
                    .get::<_, i64>(0))
                .unwrap(),
            0
        );
        db.write(&sample(
            base + 16_000_000_000,
            "baseline",
            &json!({"cpu_busy_pct":30}),
            &[],
        ))
        .unwrap();
        let (count, values, coverage): (i64, String, String) = db
            .conn
            .query_row(
                "SELECT sample_count,values_json,coverage_json FROM host_rollups",
                [],
                |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
            )
            .unwrap();
        assert_eq!(count, 3);
        assert_eq!(
            serde_json::from_str::<Value>(&values).unwrap()["cpu_busy_pct"]["mean"],
            20.0
        );
        let coverage: Value = serde_json::from_str(&coverage).unwrap();
        assert_eq!(coverage["cpu_busy_pct_unavailable_count"], 1);
        assert_eq!(coverage["gap_count"], 1);
        db.write(&sample(
            base + 20_000_000_000,
            "baseline",
            &json!({"cpu_busy_pct":50}),
            &[],
        ))
        .unwrap();
        drop(db);
        let db = Store::open(dir.path(), "h", "b").unwrap();
        assert_eq!(
            db.conn
                .query_row("SELECT sample_count FROM host_rollups", [], |r| r
                    .get::<_, i64>(0))
                .unwrap(),
            4
        );
    }
}
