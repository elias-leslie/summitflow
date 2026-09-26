use chrono::Utc;
use serde_json::{Value, json};
use std::{
    collections::{HashMap, HashSet},
    env, fs,
    io::{self, Write},
    path::Path,
    thread,
    time::{Duration, Instant},
};
use sysinfo::System;

#[derive(Clone)]
struct Proc {
    pid: u32,
    start: u64,
    name: String,
    user: u64,
    system: u64,
    rss: u64,
    read: Option<u64>,
    write: Option<u64>,
}
impl Proc {
    fn value(&self, reasons: Vec<&str>) -> Value {
        json!({"pid":self.pid,"start_ticks":self.start,"name":self.name,"cpu_user_ns":self.user,"cpu_system_ns":self.system,"rss_bytes":self.rss,"read_bytes":self.read,"write_bytes":self.write,"leader_reasons":reasons})
    }
}
struct Config {
    mode: String,
    samples: usize,
    interval: Duration,
    cgroup: Option<String>,
}
fn config() -> Result<Config, String> {
    let mut mode = None;
    let mut samples = None;
    let mut interval = None;
    let mut cgroup = None;
    let mut args = env::args().skip(1);
    while let Some(arg) = args.next() {
        let v = args
            .next()
            .ok_or_else(|| format!("missing value for {arg}"))?;
        match arg.as_str() {
            "--mode" if v == "baseline" || v == "detail" => mode = Some(v),
            "--samples" => samples = Some(v.parse::<usize>().map_err(|_| "invalid samples")?),
            "--interval-ms" => {
                interval = Some(v.parse::<u64>().map_err(|_| "invalid interval-ms")?)
            }
            "--service-cgroup" => cgroup = Some(v),
            _ => return Err(format!("invalid argument {arg}")),
        }
    }
    let mode = mode.ok_or("--mode is required")?;
    let samples = samples.ok_or("--samples is required")?;
    if samples == 0 {
        return Err("--samples must be positive".into());
    }
    let interval = interval.unwrap_or(if mode == "baseline" { 5000 } else { 1000 });
    if interval == 0 {
        return Err("--interval-ms must be positive".into());
    }
    Ok(Config {
        mode,
        samples,
        interval: Duration::from_millis(interval),
        cgroup,
    })
}
fn err(errors: &mut Vec<Value>, source: &str, code: &str) {
    if !errors
        .iter()
        .any(|e| e["source"] == source && e["code"] == code)
    {
        errors.push(json!({"source":source,"code":code}));
    }
}
fn read(path: &str, errors: &mut Vec<Value>) -> Option<String> {
    match fs::read_to_string(path) {
        Ok(s) => Some(s),
        Err(e) => {
            err(
                errors,
                path,
                if e.kind() == io::ErrorKind::PermissionDenied {
                    "permission_denied"
                } else if e.kind() == io::ErrorKind::NotFound {
                    "not_found"
                } else {
                    "read_failed"
                },
            );
            None
        }
    }
}
fn parse_num(s: Option<&str>) -> Option<u64> {
    s?.parse().ok()
}
fn mem(sys: &mut System, errors: &mut Vec<Value>) -> (Value, Value, Value) {
    sys.refresh_memory();
    if sys.total_memory() == 0 {
        err(errors, "sysinfo/memory", "unavailable");
        return (Value::Null, Value::Null, Value::Null);
    }
    (
        json!(sys.total_memory()),
        json!(sys.available_memory()),
        json!(sys.total_swap().saturating_sub(sys.free_swap())),
    )
}
fn cpu(errors: &mut Vec<Value>) -> Option<(u64, u64)> {
    let s = read("/proc/stat", errors)?;
    let line = s.lines().next()?;
    let n: Vec<u64> = line
        .split_whitespace()
        .skip(1)
        .filter_map(|x| x.parse().ok())
        .collect();
    if n.len() < 4 {
        err(errors, "/proc/stat", "parse_failed");
        return None;
    }
    Some((n.iter().sum(), n[3] + n.get(4).copied().unwrap_or(0)))
}
fn psi(kind: &str, errors: &mut Vec<Value>) -> Value {
    let path = format!("/proc/pressure/{kind}");
    let Some(s) = read(&path, errors) else {
        return Value::Null;
    };
    let val = s
        .lines()
        .find(|l| l.starts_with("some "))
        .and_then(|l| l.split_whitespace().find_map(|p| p.strip_prefix("avg10=")))
        .and_then(|x| x.parse::<f64>().ok());
    if val.is_none() {
        err(errors, &path, "parse_failed");
    }
    json!(val)
}
fn net(errors: &mut Vec<Value>) -> (Value, Value) {
    let Some(s) = read("/proc/net/dev", errors) else {
        return (Value::Null, Value::Null);
    };
    let mut rx = 0u64;
    let mut tx = 0u64;
    for line in s.lines().skip(2) {
        let Some((iface, data)) = line.split_once(':') else {
            continue;
        };
        if iface.trim() == "lo" {
            continue;
        }
        let v: Vec<&str> = data.split_whitespace().collect();
        let (Some(r), Some(t)) = (parse_num(v.first().copied()), parse_num(v.get(8).copied()))
        else {
            err(errors, "/proc/net/dev", "parse_failed");
            return (Value::Null, Value::Null);
        };
        rx = rx.saturating_add(r);
        tx = tx.saturating_add(t);
    }
    (json!(rx), json!(tx))
}
fn eligible_block(name: &str) -> bool {
    !name.starts_with("loop") && !name.starts_with("ram")
}
fn disks(errors: &mut Vec<Value>) -> (Value, Value) {
    let blocks = match fs::read_dir("/sys/block") {
        Ok(entries) => entries
            .filter_map(Result::ok)
            .map(|entry| entry.file_name().to_string_lossy().into_owned())
            .filter(|name| eligible_block(name))
            .collect::<HashSet<_>>(),
        Err(e) => {
            err(
                errors,
                "/sys/block",
                if e.kind() == io::ErrorKind::PermissionDenied {
                    "permission_denied"
                } else {
                    "read_failed"
                },
            );
            return (Value::Null, Value::Null);
        }
    };
    let Some(s) = read("/proc/diskstats", errors) else {
        return (Value::Null, Value::Null);
    };
    let mut r = 0u64;
    let mut w = 0u64;
    let mut matched = 0;
    for line in s.lines() {
        let v: Vec<&str> = line.split_whitespace().collect();
        if v.len() < 10 || !blocks.contains(v[2]) {
            continue;
        }
        let (Some(a), Some(b)) = (parse_num(v.get(5).copied()), parse_num(v.get(9).copied()))
        else {
            err(errors, "/proc/diskstats", "parse_failed");
            return (Value::Null, Value::Null);
        };
        matched += 1;
        r = r.saturating_add(a.saturating_mul(512));
        w = w.saturating_add(b.saturating_mul(512));
    }
    if matched == 0 {
        err(errors, "/proc/diskstats", "no_whole_devices");
        return (Value::Null, Value::Null);
    }
    (json!(r), json!(w))
}
fn root_disk(errors: &mut Vec<Value>) -> (Value, Value) {
    let path = std::ffi::CString::new("/").unwrap();
    let mut stat = std::mem::MaybeUninit::<libc::statvfs>::uninit();
    if unsafe { libc::statvfs(path.as_ptr(), stat.as_mut_ptr()) } != 0 {
        err(errors, "/", "statvfs_failed");
        return (Value::Null, Value::Null);
    }
    let stat = unsafe { stat.assume_init() };
    (
        json!((stat.f_blocks as u64).saturating_mul(stat.f_frsize as u64)),
        json!((stat.f_bavail as u64).saturating_mul(stat.f_frsize as u64)),
    )
}
fn proc_io(path: &str, errors: &mut Vec<Value>) -> (Option<u64>, Option<u64>, bool) {
    let s = match fs::read_to_string(path) {
        Ok(s) => s,
        Err(e) => {
            let denied = e.kind() == io::ErrorKind::PermissionDenied;
            err(
                errors,
                "/proc/*/io",
                if denied {
                    "permission_denied"
                } else if e.kind() == io::ErrorKind::NotFound {
                    "not_found"
                } else {
                    "read_failed"
                },
            );
            return (None, None, denied);
        }
    };
    let find = |k: &str| {
        s.lines()
            .find_map(|l| l.strip_prefix(k).and_then(|x| x.trim().parse().ok()))
    };
    let a = find("read_bytes:");
    let b = find("write_bytes:");
    if a.is_none() || b.is_none() {
        err(errors, "/proc/*/io", "parse_failed");
    }
    (a, b, false)
}
fn processes(errors: &mut Vec<Value>) -> (Vec<Proc>, u64, u64, u64) {
    let mut out = Vec::new();
    let mut seen = 0;
    let mut denied = 0;
    let mut exited = 0;
    let Ok(entries) = fs::read_dir("/proc") else {
        err(errors, "/proc", "read_failed");
        return (out, seen, denied, exited);
    };
    let ticks = unsafe { libc::sysconf(libc::_SC_CLK_TCK) };
    let pages = unsafe { libc::sysconf(libc::_SC_PAGESIZE) };
    if ticks <= 0 || pages <= 0 {
        err(errors, "sysconf", "unavailable");
        return (out, seen, denied, exited);
    }
    for entry in entries.flatten() {
        let Ok(pid) = entry.file_name().to_string_lossy().parse::<u32>() else {
            continue;
        };
        seen += 1;
        let stat_path = format!("/proc/{pid}/stat");
        let s = match fs::read_to_string(&stat_path) {
            Ok(v) => v,
            Err(e) => {
                if e.kind() == io::ErrorKind::PermissionDenied {
                    denied += 1
                } else {
                    exited += 1
                }
                continue;
            }
        };
        let Some(open) = s.find('(') else {
            err(errors, "/proc/*/stat", "parse_failed");
            continue;
        };
        let Some(close) = s.rfind(')') else {
            err(errors, "/proc/*/stat", "parse_failed");
            continue;
        };
        let name = s[open + 1..close].to_string();
        let v: Vec<&str> = s[close + 1..].split_whitespace().collect();
        let (Some(user), Some(system), Some(start), Some(rss)) = (
            parse_num(v.get(11).copied()),
            parse_num(v.get(12).copied()),
            parse_num(v.get(19).copied()),
            parse_num(v.get(21).copied()),
        ) else {
            err(errors, "/proc/*/stat", "parse_failed");
            continue;
        };
        let io_path = format!("/proc/{pid}/io");
        let (read, write, io_denied) = proc_io(&io_path, errors);
        if io_denied {
            denied += 1;
        }
        out.push(Proc {
            pid,
            start,
            name,
            user: user.saturating_mul(1_000_000_000) / (ticks as u64),
            system: system.saturating_mul(1_000_000_000) / (ticks as u64),
            rss: rss.saturating_mul(pages as u64),
            read,
            write,
        });
    }
    (out, seen, denied, exited)
}
fn leaders(procs: &[Proc], prev: &HashMap<(u32, u64), Proc>) -> Vec<Value> {
    let mut reasons: HashMap<(u32, u64), Vec<&str>> = HashMap::new();
    let mut cpu: Vec<_> = procs
        .iter()
        .filter_map(|p| {
            let q = prev.get(&(p.pid, p.start))?;
            Some((
                p.user
                    .saturating_add(p.system)
                    .checked_sub(q.user.saturating_add(q.system))?,
                p,
            ))
        })
        .collect();
    cpu.sort_by(|a, b| {
        b.0.cmp(&a.0)
            .then(a.1.pid.cmp(&b.1.pid))
            .then(a.1.start.cmp(&b.1.start))
    });
    for (_, p) in cpu.into_iter().take(10) {
        reasons.entry((p.pid, p.start)).or_default().push("cpu");
    }
    let mut rss: Vec<_> = procs.iter().collect();
    rss.sort_by(|a, b| {
        b.rss
            .cmp(&a.rss)
            .then(a.pid.cmp(&b.pid))
            .then(a.start.cmp(&b.start))
    });
    for p in rss.into_iter().take(10) {
        reasons.entry((p.pid, p.start)).or_default().push("rss");
    }
    let mut io: Vec<_> = procs
        .iter()
        .filter_map(|p| {
            let q = prev.get(&(p.pid, p.start))?;
            Some((
                p.read?
                    .checked_sub(q.read?)?
                    .saturating_add(p.write?.checked_sub(q.write?)?),
                p,
            ))
        })
        .collect();
    io.sort_by(|a, b| {
        b.0.cmp(&a.0)
            .then(a.1.pid.cmp(&b.1.pid))
            .then(a.1.start.cmp(&b.1.start))
    });
    for (_, p) in io.into_iter().take(10) {
        reasons.entry((p.pid, p.start)).or_default().push("io");
    }
    let mut rows: Vec<_> = procs
        .iter()
        .filter(|p| reasons.contains_key(&(p.pid, p.start)))
        .collect();
    rows.sort_by_key(|p| (p.pid, p.start));
    rows.into_iter()
        .map(|p| p.value(reasons.remove(&(p.pid, p.start)).unwrap_or_default()))
        .collect()
}
fn service(path: &str, errors: &mut Vec<Value>) -> Value {
    let base = Path::new(path);
    let mut read_field = |file: &str| read(&base.join(file).to_string_lossy(), errors);
    let cpu = read_field("cpu.stat").and_then(|s| {
        s.lines().find_map(|l| {
            l.strip_prefix("usage_usec ")
                .and_then(|x| x.parse::<u64>().ok())
        })
    });
    let memory = read_field("memory.current").and_then(|s| s.trim().parse::<u64>().ok());
    let io = read_field("io.stat");
    let mut r = None;
    let mut w = None;
    if let Some(s) = io {
        let mut rb = 0u64;
        let mut wb = 0u64;
        let mut gotr = false;
        let mut gotw = false;
        for l in s.lines() {
            for p in l.split_whitespace().skip(1) {
                if let Some(x) = p
                    .strip_prefix("rbytes=")
                    .and_then(|v| v.parse::<u64>().ok())
                {
                    rb = rb.saturating_add(x);
                    gotr = true
                }
                if let Some(x) = p
                    .strip_prefix("wbytes=")
                    .and_then(|v| v.parse::<u64>().ok())
                {
                    wb = wb.saturating_add(x);
                    gotw = true
                }
            }
        }
        if gotr {
            r = Some(rb)
        }
        if gotw {
            w = Some(wb)
        }
    }
    if cpu.is_none() {
        err(errors, "cgroup2/cpu.stat", "unavailable")
    }
    if memory.is_none() {
        err(errors, "cgroup2/memory.current", "unavailable")
    }
    if r.is_none() || w.is_none() {
        err(errors, "cgroup2/io.stat", "unavailable")
    }
    service_value(cpu, memory, r, w)
}
fn service_value(
    cpu: Option<u64>,
    memory: Option<u64>,
    read: Option<u64>,
    write: Option<u64>,
) -> Value {
    json!({"source":"cgroup2","cpu_usage_usec":cpu,"memory_current_bytes":memory,"io_read_bytes":read,"io_write_bytes":write})
}
fn main() -> Result<(), Box<dyn std::error::Error>> {
    let cfg = config().map_err(|s| io::Error::new(io::ErrorKind::InvalidInput, s))?;
    let mut sys = System::new();
    let mut prev_time = None;
    let mut prev_cpu = None;
    let mut prev_procs = HashMap::new();
    let mut target = Instant::now();
    for i in 0..cfg.samples {
        if i > 0 {
            target += cfg.interval;
            let now = Instant::now();
            if target > now {
                thread::sleep(target - now)
            }
        }
        let start = Instant::now();
        let timestamp = Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Nanos, true);
        let mut errors = Vec::new();
        let cpu_now = cpu(&mut errors);
        let busy = match (prev_cpu, cpu_now) {
            (Some((pt, pi)), Some((ct, ci))) if ct > pt => Some(
                100.0 * ((ct - pt).saturating_sub(ci.saturating_sub(pi))) as f64 / (ct - pt) as f64,
            ),
            _ => None,
        };
        let (total, available, swap) = mem(&mut sys, &mut errors);
        let (disk_total, disk_free) = root_disk(&mut errors);
        let (rx, tx) = net(&mut errors);
        let (disk_read, disk_write) = disks(&mut errors);
        let host = json!({"cpu_busy_pct":busy,"memory_total_bytes":total,"memory_available_bytes":available,"swap_used_bytes":swap,"disk_total_bytes":disk_total,"disk_free_bytes":disk_free,"cpu_some_avg10_pct":psi("cpu",&mut errors),"memory_some_avg10_pct":psi("memory",&mut errors),"io_some_avg10_pct":psi("io",&mut errors),"net_rx_bytes":rx,"net_tx_bytes":tx,"disk_read_bytes":disk_read,"disk_write_bytes":disk_write});
        let (procs, seen, denied, exited) = processes(&mut errors);
        let rows = if cfg.mode == "detail" {
            procs
                .iter()
                .map(|p| p.value(Vec::new()))
                .collect::<Vec<_>>()
        } else {
            leaders(&procs, &prev_procs)
        };
        let svc = cfg.cgroup.as_deref().map(|p| service(p, &mut errors));
        let elapsed = prev_time.map(|t: Instant| start.duration_since(t).as_nanos() as u64);
        let result = json!({"schema":1,"sampled_at":timestamp,"elapsed_ns":elapsed,"mode":cfg.mode,"provider":"rust-sysinfo-proc","duration_ns":start.elapsed().as_nanos() as u64,"host":host,"service":svc,"processes":rows,"processes_seen":seen,"processes_permission_denied":denied,"processes_exited":exited,"errors":errors});
        writeln!(io::stdout().lock(), "{}", result)?;
        prev_time = Some(start);
        prev_cpu = cpu_now;
        prev_procs = procs.into_iter().map(|p| ((p.pid, p.start), p)).collect();
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    fn process(pid: u32, rss: u64, user: u64, read: Option<u64>) -> Proc {
        Proc {
            pid,
            start: 7,
            name: format!("p{pid}"),
            user,
            system: 0,
            rss,
            read,
            write: read,
        }
    }
    #[test]
    fn service_json_uses_contract_keys_and_usec_units() {
        let value = service_value(Some(123), Some(456), Some(789), None);
        let object = value.as_object().unwrap();
        let keys: Vec<_> = object.keys().map(String::as_str).collect();
        assert_eq!(
            keys,
            [
                "cpu_usage_usec",
                "io_read_bytes",
                "io_write_bytes",
                "memory_current_bytes",
                "source"
            ]
        );
        assert_eq!(value["cpu_usage_usec"], 123);
        assert_eq!(value["io_read_bytes"], 789);
        assert!(value["io_write_bytes"].is_null());
    }
    #[test]
    fn block_selection_excludes_loop_and_ram() {
        assert!(!eligible_block("loop20"));
        assert!(!eligible_block("ram0"));
        assert!(eligible_block("nvme0n1"));
        assert!(eligible_block("sda"));
    }
    #[test]
    fn first_baseline_has_only_rss_leaders() {
        let rows = leaders(
            &[process(2, 20, 50, Some(50)), process(1, 10, 100, Some(100))],
            &HashMap::new(),
        );
        assert_eq!(rows.len(), 2);
        assert!(rows.iter().all(|r| r["leader_reasons"] == json!(["rss"])));
    }
    #[test]
    fn leader_deltas_require_same_start_and_available_io() {
        let old = process(1, 10, 0, Some(0));
        let mut previous = HashMap::new();
        previous.insert((old.pid, old.start), old);
        let rows = leaders(
            &[process(1, 20, 10, Some(10)), process(2, 30, 100, None)],
            &previous,
        );
        let one = rows.iter().find(|r| r["pid"] == 1).unwrap();
        let two = rows.iter().find(|r| r["pid"] == 2).unwrap();
        assert_eq!(one["leader_reasons"], json!(["cpu", "rss", "io"]));
        assert_eq!(two["leader_reasons"], json!(["rss"]));
    }
}
