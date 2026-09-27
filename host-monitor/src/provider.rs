use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, HashMap, HashSet},
    fs,
    io::{self, Read},
    os::{fd::AsRawFd, unix::fs::MetadataExt},
    path::Path,
    process::{ChildStdout, Command, Stdio},
    sync::OnceLock,
    thread,
    time::{Duration, Instant},
};
use sysinfo::System;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ProcState {
    Running,
    Sleeping,
    DiskSleep,
    Stopped,
    TracingStop,
    Zombie,
    Dead,
    DeadLower,
    Wakekill,
    Waking,
    Parked,
    Idle,
    Unknown,
}
impl ProcState {
    fn from_code(code: Option<&str>) -> Self {
        match code {
            Some("R") => Self::Running,
            Some("S") => Self::Sleeping,
            Some("D") => Self::DiskSleep,
            Some("T") => Self::Stopped,
            Some("t") => Self::TracingStop,
            Some("Z") => Self::Zombie,
            Some("X") => Self::Dead,
            Some("x") => Self::DeadLower,
            Some("K") => Self::Wakekill,
            Some("W") => Self::Waking,
            Some("P") => Self::Parked,
            Some("I") => Self::Idle,
            _ => Self::Unknown,
        }
    }
    fn code(self) -> &'static str {
        match self {
            Self::Running => "R",
            Self::Sleeping => "S",
            Self::DiskSleep => "D",
            Self::Stopped => "T",
            Self::TracingStop => "t",
            Self::Zombie => "Z",
            Self::Dead => "X",
            Self::DeadLower => "x",
            Self::Wakekill => "K",
            Self::Waking => "W",
            Self::Parked => "P",
            Self::Idle => "I",
            Self::Unknown => "?",
        }
    }
    fn label(self) -> &'static str {
        match self {
            Self::Running => "running",
            Self::Sleeping => "sleeping",
            Self::DiskSleep => "uninterruptible_sleep",
            Self::Stopped => "stopped",
            Self::TracingStop => "tracing_stop",
            Self::Zombie => "zombie",
            Self::Dead | Self::DeadLower => "dead",
            Self::Wakekill => "wakekill",
            Self::Waking => "waking",
            Self::Parked => "parked",
            Self::Idle => "idle",
            Self::Unknown => "unknown",
        }
    }
}

#[derive(Clone)]
pub struct Proc {
    pub pid: u32,
    pub ppid: u32,
    pub state: ProcState,
    pub start: u64,
    pub name: String,
    pub user: u64,
    pub system: u64,
    pub rss: u64,
    pub read: Option<u64>,
    pub write: Option<u64>,
    pub uid: Option<u32>,
    pub service: Option<String>,
}
impl Proc {
    pub fn value(&self, reasons: Vec<&str>) -> Value {
        json!({"pid":self.pid,"ppid":self.ppid,"state":self.state.label(),"state_code":self.state.code(),"start_ticks":self.start,"name":self.name,"cpu_user_ns":self.user,"cpu_system_ns":self.system,"rss_bytes":self.rss,"read_bytes":self.read,"write_bytes":self.write,"uid":self.uid,"user":self.uid.and_then(username),"service":self.service,"leader_reasons":reasons})
    }
}
static USERS: OnceLock<HashMap<u32, String>> = OnceLock::new();
fn username(uid: u32) -> Option<String> {
    USERS
        .get_or_init(|| parse_passwd(&fs::read_to_string("/etc/passwd").unwrap_or_default()))
        .get(&uid)
        .cloned()
}
fn parse_passwd(contents: &str) -> HashMap<u32, String> {
    contents
        .lines()
        .filter_map(|line| {
            let fields = line.split(':').collect::<Vec<_>>();
            Some((
                fields.get(2)?.parse::<u32>().ok()?,
                fields.first()?.to_string(),
            ))
        })
        .collect()
}
fn err(errors: &mut Vec<Value>, source: &str, code: &str) {
    if !errors
        .iter()
        .any(|e| e["source"] == source && e["code"] == code)
    {
        errors.push(json!({"source":source,"code":code}));
    }
}

const GPU_SOURCE: &str = "nvidia-smi";
const GPU_MAX_DEVICES: usize = 32;
const GPU_MAX_OUTPUT_BYTES: u64 = 8192;
const GPU_TIMEOUT: Duration = Duration::from_millis(500);

pub fn gpu_unavailable(code: &str) -> Value {
    json!({"provider":GPU_SOURCE,"availability":code,"devices":[],"devices_seen":0,"devices_scanned":0,"missing_fields":{},"max_utilization_pct":null,"memory_used_bytes":null,"memory_total_bytes":null})
}

fn gpu_csv_line(line: &str) -> Option<Vec<String>> {
    let mut cells = Vec::new();
    let mut cell = String::new();
    let mut quoted = false;
    let mut chars = line.chars().peekable();
    while let Some(ch) = chars.next() {
        match ch {
            '"' if quoted && chars.peek() == Some(&'"') => {
                cell.push('"');
                chars.next();
            }
            '"' => quoted = !quoted,
            ',' if !quoted => {
                cells.push(cell.trim().to_owned());
                cell.clear();
            }
            c if !c.is_control() => cell.push(c),
            _ => return None,
        }
    }
    if quoted {
        return None;
    }
    cells.push(cell.trim().to_owned());
    Some(cells)
}

fn gpu_number(raw: &str, max: f64) -> Option<f64> {
    raw.parse::<f64>()
        .ok()
        .filter(|number| number.is_finite() && *number >= 0.0 && *number <= max)
}

fn gpu_from_csv(output: &str, errors: &mut Vec<Value>) -> Value {
    let mut devices = Vec::new();
    let mut indexes = HashSet::new();
    let mut missing = BTreeMap::<&'static str, usize>::new();
    let mut seen = 0;
    let mut used = 0u64;
    let mut total = 0u64;
    let mut memory_complete = true;
    let mut utilization_complete = true;
    let mut busy: Option<f64> = None;
    for line in output.lines().filter(|line| !line.trim().is_empty()) {
        seen += 1;
        if seen > GPU_MAX_DEVICES {
            err(errors, GPU_SOURCE, "source_truncated");
            memory_complete = false;
            utilization_complete = false;
            continue;
        }
        let Some(fields) = gpu_csv_line(line).filter(|fields| fields.len() == 7) else {
            err(errors, GPU_SOURCE, "parse_failed");
            memory_complete = false;
            utilization_complete = false;
            continue;
        };
        let Ok(index) = fields[0].parse::<u32>() else {
            err(errors, GPU_SOURCE, "parse_failed");
            memory_complete = false;
            utilization_complete = false;
            continue;
        };
        if !indexes.insert(index) {
            err(errors, GPU_SOURCE, "parse_failed");
            memory_complete = false;
            utilization_complete = false;
            continue;
        }
        let name: String = fields[1].chars().take(64).collect();
        let utilization = gpu_number(&fields[2], 100.0);
        if utilization.is_none() {
            utilization_complete = false;
        }
        let mut memory_used =
            gpu_number(&fields[3], 1_000_000_000.0).map(|n| (n * 1024.0 * 1024.0) as u64);
        let memory_total =
            gpu_number(&fields[4], 1_000_000_000.0).map(|n| (n * 1024.0 * 1024.0) as u64);
        let temperature = gpu_number(&fields[5], 150.0);
        let power = gpu_number(&fields[6], 100_000.0);
        if let (Some(a), Some(b)) = (memory_used, memory_total) {
            if a <= b {
                used = used.saturating_add(a);
                total = total.saturating_add(b);
            } else {
                err(errors, GPU_SOURCE, "parse_failed");
                memory_used = None;
                memory_complete = false;
            }
        } else {
            memory_complete = false;
        }
        for (field, absent) in [
            ("utilization_pct", utilization.is_none()),
            ("memory_used_bytes", memory_used.is_none()),
            ("memory_total_bytes", memory_total.is_none()),
            ("temperature_c", temperature.is_none()),
            ("power_w", power.is_none()),
        ] {
            if absent {
                *missing.entry(field).or_default() += 1;
            }
        }
        if let Some(value) = utilization {
            busy = Some(busy.map_or(value, |prior| prior.max(value)));
        }
        devices.push(json!({"index":index,"name":name,"utilization_pct":utilization,"memory_used_bytes":memory_used,"memory_total_bytes":memory_total,"temperature_c":temperature,"power_w":power}));
    }
    if devices.is_empty() {
        let mut unavailable = gpu_unavailable(if seen == 0 { "unsupported" } else { "error" });
        unavailable["devices_seen"] = json!(seen);
        return unavailable;
    }
    if !missing.is_empty() {
        err(errors, GPU_SOURCE, "field_unavailable");
    }
    json!({"provider":GPU_SOURCE,"availability":if errors.iter().any(|e| e["source"] == GPU_SOURCE) {"partial"} else {"ok"},"devices":devices,"devices_seen":seen,"devices_scanned":devices.len(),"missing_fields":missing,"max_utilization_pct":if utilization_complete {busy} else {None},"memory_used_bytes":if memory_complete && total > 0 {Some(used)} else {None},"memory_total_bytes":if memory_complete && total > 0 {Some(total)} else {None}})
}

fn gpu_drain_output(stream: &mut ChildStdout, bytes: &mut Vec<u8>) -> io::Result<bool> {
    let mut chunk = [0u8; 1024];
    loop {
        let allowed = ((GPU_MAX_OUTPUT_BYTES + 1) as usize - bytes.len()).min(chunk.len());
        if allowed == 0 {
            return Ok(true);
        }
        match stream.read(&mut chunk[..allowed]) {
            Ok(0) => return Ok(false),
            Ok(n) => bytes.extend_from_slice(&chunk[..n]),
            Err(e) if e.kind() == io::ErrorKind::WouldBlock => return Ok(false),
            Err(e) => return Err(e),
        }
    }
}

pub fn gpu(command_path: &Path, errors: &mut Vec<Value>) -> Value {
    let mut child = match Command::new(command_path)
        .args(["--query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw", "--format=csv,noheader,nounits"])
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
    {
        Ok(child) => child,
        Err(e) => {
            let code = match e.kind() {
                io::ErrorKind::NotFound => "unsupported",
                io::ErrorKind::PermissionDenied => "permission_denied",
                _ => "error",
            };
            if code != "unsupported" {
                err(errors, GPU_SOURCE, code);
            }
            return gpu_unavailable(code);
        }
    };
    let mut stream = child.stdout.take().expect("requested piped stdout");
    let fd = stream.as_raw_fd();
    let flags = unsafe { libc::fcntl(fd, libc::F_GETFL) };
    if flags < 0 || unsafe { libc::fcntl(fd, libc::F_SETFL, flags | libc::O_NONBLOCK) } < 0 {
        let _ = child.kill();
        let _ = child.wait();
        err(errors, GPU_SOURCE, "error");
        return gpu_unavailable("error");
    }
    let mut bytes = Vec::new();
    let started = Instant::now();
    let result = loop {
        match gpu_drain_output(&mut stream, &mut bytes) {
            Ok(true) => break Err("source_truncated"),
            Err(_) => break Err("error"),
            Ok(false) => {}
        }
        match child.try_wait() {
            Ok(Some(status)) => match gpu_drain_output(&mut stream, &mut bytes) {
                Ok(true) => break Err("source_truncated"),
                Err(_) => break Err("error"),
                Ok(false) => break Ok(status),
            },
            Ok(None) if started.elapsed() < GPU_TIMEOUT => thread::sleep(Duration::from_millis(10)),
            Ok(None) => break Err("timeout"),
            Err(_) => break Err("error"),
        }
    };
    let status = match result {
        Ok(status) => status,
        Err(code) => {
            let _ = child.kill();
            let _ = child.wait();
            err(errors, GPU_SOURCE, code);
            return gpu_unavailable(code);
        }
    };
    if !status.success() {
        err(errors, GPU_SOURCE, "error");
        return gpu_unavailable("error");
    }
    match std::str::from_utf8(&bytes) {
        Ok(output) => gpu_from_csv(output, errors),
        Err(_) => {
            err(errors, GPU_SOURCE, "parse_failed");
            gpu_unavailable("error")
        }
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
fn parse_ppid(fields: &[&str]) -> Option<u32> {
    fields.get(1)?.parse().ok()
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
pub fn cpu(errors: &mut Vec<Value>) -> Option<(u64, u64)> {
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
fn source_set(kind: &str, mut names: Vec<String>) -> Value {
    names.sort_unstable();
    names.dedup();
    json!(format!("{kind}:{}", json!(names)))
}
const MAX_COUNTER_MEMBERS: usize = 64;

fn net_counters(
    s: &str,
    errors: &mut Vec<Value>,
    identity: impl Fn(&str) -> Option<String>,
) -> (Value, Value, Value, Value) {
    let mut rx = 0u64;
    let mut tx = 0u64;
    let mut names = Vec::new();
    let mut members = BTreeMap::new();
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
            return (Value::Null, Value::Null, Value::Null, Value::Null);
        };
        let name = iface.trim().to_owned();
        names.push(name.clone());
        members.insert(name.clone(), json!([r, t, identity(&name)]));
        rx = rx.saturating_add(r);
        tx = tx.saturating_add(t);
    }
    if members.len() > MAX_COUNTER_MEMBERS {
        err(errors, "/proc/net/dev", "too_many_sources");
        return (Value::Null, Value::Null, Value::Null, Value::Null);
    }
    (
        json!(rx),
        json!(tx),
        source_set("net", names),
        json!(members),
    )
}
fn net(errors: &mut Vec<Value>) -> (Value, Value, Value, Value) {
    let Some(s) = read("/proc/net/dev", errors) else {
        return (Value::Null, Value::Null, Value::Null, Value::Null);
    };
    net_counters(&s, errors, |name| {
        fs::read_to_string(Path::new("/sys/class/net").join(name).join("ifindex"))
            .ok()
            .and_then(|value| value.trim().parse::<u32>().ok())
            .map(|index| index.to_string())
    })
}
fn eligible_block(name: &str) -> bool {
    !name.starts_with("loop") && !name.starts_with("ram")
}
fn disk_counters(
    s: &str,
    blocks: &HashSet<String>,
    errors: &mut Vec<Value>,
    identity: impl Fn(&str) -> Option<String>,
) -> (Value, Value, Value, Value) {
    let mut r = 0u64;
    let mut w = 0u64;
    let mut matched = Vec::new();
    let mut members = BTreeMap::new();
    for line in s.lines() {
        let v: Vec<&str> = line.split_whitespace().collect();
        if v.len() < 10 || !blocks.contains(v[2]) {
            continue;
        }
        let (Some(a), Some(b)) = (parse_num(v.get(5).copied()), parse_num(v.get(9).copied()))
        else {
            err(errors, "/proc/diskstats", "parse_failed");
            return (Value::Null, Value::Null, Value::Null, Value::Null);
        };
        let name = v[2].to_owned();
        let read = a.saturating_mul(512);
        let write = b.saturating_mul(512);
        matched.push(name.clone());
        members.insert(name.clone(), json!([read, write, identity(&name)]));
        r = r.saturating_add(read);
        w = w.saturating_add(write);
    }
    if matched.is_empty() {
        err(errors, "/proc/diskstats", "no_whole_devices");
        return (Value::Null, Value::Null, Value::Null, Value::Null);
    }
    if members.len() > MAX_COUNTER_MEMBERS {
        err(errors, "/proc/diskstats", "too_many_sources");
        return (Value::Null, Value::Null, Value::Null, Value::Null);
    }
    (
        json!(r),
        json!(w),
        source_set("disk", matched),
        json!(members),
    )
}
fn disk_instance(dev: Option<&str>, diskseq: Option<&str>) -> Option<String> {
    let (major, minor) = dev?.trim().split_once(':')?;
    let major = major.parse::<u32>().ok()?;
    let minor = minor.parse::<u32>().ok()?;
    let device = format!("{major}:{minor}");
    Some(
        match diskseq.and_then(|value| value.trim().parse::<u64>().ok()) {
            Some(sequence) => format!("{device}@{sequence}"),
            None => device,
        },
    )
}
fn disks(errors: &mut Vec<Value>) -> (Value, Value, Value, Value) {
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
            return (Value::Null, Value::Null, Value::Null, Value::Null);
        }
    };
    let Some(s) = read("/proc/diskstats", errors) else {
        return (Value::Null, Value::Null, Value::Null, Value::Null);
    };
    disk_counters(&s, &blocks, errors, |name| {
        let device = Path::new("/sys/block").join(name);
        let dev = fs::read_to_string(device.join("dev")).ok();
        let diskseq = fs::read_to_string(device.join("diskseq")).ok();
        disk_instance(dev.as_deref(), diskseq.as_deref())
    })
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
fn proc_io(
    result: io::Result<String>,
    errors: &mut Vec<Value>,
) -> (Option<u64>, Option<u64>, bool) {
    let s = match result {
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

#[derive(Clone, Copy, Default)]
pub struct ProcessCounts {
    pub seen: u64,
    pub stat_denied: u64,
    pub io_denied: u64,
    pub exited: u64,
}

fn process_from_stat(
    pid: u32,
    s: &str,
    ticks: u64,
    pages: u64,
    io_result: io::Result<String>,
    uid: Option<u32>,
    service: Option<String>,
    errors: &mut Vec<Value>,
) -> Option<(Proc, bool)> {
    let open = s.find('(');
    let close = s.rfind(')');
    let (Some(open), Some(close)) = (open, close) else {
        err(errors, "/proc/*/stat", "parse_failed");
        return None;
    };
    if close <= open {
        err(errors, "/proc/*/stat", "parse_failed");
        return None;
    }
    let name = s[open + 1..close].to_string();
    let v: Vec<&str> = s[close + 1..].split_whitespace().collect();
    let (Some(ppid), Some(user), Some(system), Some(start), Some(rss)) = (
        parse_ppid(&v),
        parse_num(v.get(11).copied()),
        parse_num(v.get(12).copied()),
        parse_num(v.get(19).copied()),
        parse_num(v.get(21).copied()),
    ) else {
        err(errors, "/proc/*/stat", "parse_failed");
        return None;
    };
    let (read, write, io_denied) = proc_io(io_result, errors);
    Some((
        Proc {
            pid,
            ppid,
            state: ProcState::from_code(v.first().copied()),
            start,
            name,
            user: user.saturating_mul(1_000_000_000) / ticks,
            system: system.saturating_mul(1_000_000_000) / ticks,
            rss: rss.saturating_mul(pages),
            read,
            write,
            uid,
            service,
        },
        io_denied,
    ))
}

pub fn processes(errors: &mut Vec<Value>, services: &[String]) -> (Vec<Proc>, ProcessCounts) {
    let mut out = Vec::new();
    let mut counts = ProcessCounts::default();
    let Ok(entries) = fs::read_dir("/proc") else {
        err(errors, "/proc", "read_failed");
        return (out, counts);
    };
    let ticks = unsafe { libc::sysconf(libc::_SC_CLK_TCK) };
    let pages = unsafe { libc::sysconf(libc::_SC_PAGESIZE) };
    if ticks <= 0 || pages <= 0 {
        err(errors, "sysconf", "unavailable");
        return (out, counts);
    }
    for entry in entries.flatten() {
        let Ok(pid) = entry.file_name().to_string_lossy().parse::<u32>() else {
            continue;
        };
        counts.seen += 1;
        let stat_path = format!("/proc/{pid}/stat");
        let s = match fs::read_to_string(&stat_path) {
            Ok(v) => v,
            Err(e) => {
                if e.kind() == io::ErrorKind::PermissionDenied {
                    counts.stat_denied += 1;
                    err(errors, "/proc/*/stat", "permission_denied");
                } else {
                    counts.exited += 1
                }
                continue;
            }
        };
        let io_path = format!("/proc/{pid}/io");
        let uid = fs::metadata(&stat_path).ok().map(|m| m.uid());
        let service = fs::read_to_string(format!("/proc/{pid}/cgroup"))
            .ok()
            .and_then(|s| service_from_cgroup(&s, services));
        let Some((process, io_denied)) = process_from_stat(
            pid,
            &s,
            ticks as u64,
            pages as u64,
            fs::read_to_string(&io_path),
            uid,
            service,
            errors,
        ) else {
            continue;
        };
        if io_denied {
            counts.io_denied += 1;
        }
        out.push(process);
    }
    (out, counts)
}
fn service_from_cgroup(cgroup: &str, services: &[String]) -> Option<String> {
    cgroup
        .lines()
        .find_map(|line| line.strip_prefix("0::"))
        .and_then(|group| {
            group.split('/').find_map(|component| {
                services
                    .iter()
                    .find(|name| name.as_str() == component)
                    .cloned()
            })
        })
}
pub fn leaders(procs: &[Proc], prev: &HashMap<(u32, u64), Proc>) -> Vec<Value> {
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
pub fn service(path: &str, errors: &mut Vec<Value>) -> Value {
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

pub fn host(
    sys: &mut System,
    prev_cpu: Option<(u64, u64)>,
    errors: &mut Vec<Value>,
) -> (Value, Option<(u64, u64)>) {
    let cpu_now = cpu(errors);
    let busy = match (prev_cpu, cpu_now) {
        (Some((pt, pi)), Some((ct, ci))) if ct > pt && ci >= pi => {
            Some(100.0 * ((ct - pt).saturating_sub(ci - pi)) as f64 / (ct - pt) as f64)
        }
        _ => None,
    };
    let (total, available, swap) = mem(sys, errors);
    let (disk_total, disk_free) = root_disk(errors);
    let (rx, tx, net_source, net_members) = net(errors);
    let (disk_read, disk_write, disk_source, disk_members) = disks(errors);
    (
        json!({"cpu_busy_pct":busy,"memory_total_bytes":total,"memory_available_bytes":available,"swap_used_bytes":swap,"disk_total_bytes":disk_total,"disk_free_bytes":disk_free,"cpu_some_avg10_pct":psi("cpu",errors),"memory_some_avg10_pct":psi("memory",errors),"io_some_avg10_pct":psi("io",errors),"net_rx_bytes":rx,"net_tx_bytes":tx,"net_source":net_source,"net_members":net_members,"disk_read_bytes":disk_read,"disk_write_bytes":disk_write,"disk_source":disk_source,"disk_members":disk_members}),
        cpu_now,
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::fs::PermissionsExt;

    #[test]
    fn gpu_csv_preserves_quoted_name_and_null_reading_without_guessing() {
        let mut errors = Vec::new();
        let result = gpu_from_csv("0, \"GPU, Model\", 25, 100, 1000, N/A, 35.5\n", &mut errors);
        assert_eq!(result["availability"], "partial");
        assert_eq!(result["devices"][0]["name"], "GPU, Model");
        assert_eq!(result["devices"][0]["temperature_c"], Value::Null);
        assert_eq!(result["missing_fields"]["temperature_c"], 1);
        assert!(
            errors
                .iter()
                .any(|error| error["code"] == "field_unavailable")
        );
        assert_eq!(result["max_utilization_pct"], 25.0);
        assert_eq!(result["memory_used_bytes"], 100 * 1024 * 1024);
    }

    #[test]
    fn gpu_partial_rows_and_excess_devices_do_not_fabricate_aggregate() {
        let mut errors = Vec::new();
        let result = gpu_from_csv(
            "0, GPU, 20, 900, 1000, 40, 50\n1, GPU, 30, N/A, 1000, 50, 60\n",
            &mut errors,
        );
        assert_eq!(result["memory_used_bytes"], Value::Null);
        assert_eq!(result["devices"][1]["memory_used_bytes"], Value::Null);
        assert_eq!(result["availability"], "partial");
        assert_eq!(result["missing_fields"]["memory_used_bytes"], 1);
        assert_eq!(result["max_utilization_pct"], 30.0);
        let rows = (0..33)
            .map(|index| {
                format!(
                    "{index}, GPU, {}, 1, 2, 40, 50\n",
                    if index == 32 { 99 } else { 20 }
                )
            })
            .collect::<String>();
        let capped = gpu_from_csv(&rows, &mut errors);
        assert_eq!(capped["devices_seen"], 33);
        assert_eq!(capped["devices_scanned"], 32);
        assert_eq!(capped["availability"], "partial");
        assert_eq!(capped["max_utilization_pct"], Value::Null);
        assert_eq!(capped["memory_used_bytes"], Value::Null);
        assert!(
            errors
                .iter()
                .any(|error| error["code"] == "source_truncated")
        );
        let duplicate = gpu_from_csv(
            "0, GPU, 20, 1, 2, 40, 50\n0, GPU, 30, 1, 2, 40, 50\n",
            &mut Vec::new(),
        );
        assert_eq!(duplicate["devices_scanned"], 1);
        assert_eq!(duplicate["availability"], "partial");
        assert_eq!(duplicate["memory_used_bytes"], Value::Null);
        assert_eq!(duplicate["max_utilization_pct"], Value::Null);
        let missing_util = gpu_from_csv(
            "0, GPU, 50, 1, 2, 40, 50\n1, GPU, N/A, 1, 2, 40, 50\n",
            &mut Vec::new(),
        );
        assert_eq!(missing_util["availability"], "partial");
        assert_eq!(missing_util["max_utilization_pct"], Value::Null);
        assert_eq!(missing_util["memory_used_bytes"], 2 * 1024 * 1024);
        assert_eq!(missing_util["missing_fields"]["utilization_pct"], 1);
    }

    #[test]
    fn gpu_command_timeout_and_permission_failure_are_bounded() {
        let dir = tempfile::tempdir().unwrap();
        let script = dir.path().join("smi");
        fs::write(&script, "#!/bin/sh\nexec sleep 2\n").unwrap();
        fs::set_permissions(&script, fs::Permissions::from_mode(0o700)).unwrap();
        let mut errors = Vec::new();
        let started = Instant::now();
        let timed = gpu(&script, &mut errors);
        assert_eq!(timed["availability"], "timeout");
        assert!(started.elapsed() < Duration::from_secs(2));
        assert!(errors.iter().any(|error| error["code"] == "timeout"));
        if unsafe { libc::geteuid() } != 0 {
            fs::set_permissions(&script, fs::Permissions::from_mode(0o000)).unwrap();
            let denied = gpu(&script, &mut Vec::new());
            assert_eq!(denied["availability"], "permission_denied");
        }
        let absent = gpu(&dir.path().join("missing"), &mut Vec::new());
        assert_eq!(absent["availability"], "unsupported");
    }

    #[test]
    fn gpu_oversized_output_is_truncated_before_pipe_stall() {
        let dir = tempfile::tempdir().unwrap();
        let script = dir.path().join("smi");
        fs::write(
            &script,
            "#!/bin/sh\nexec /usr/bin/head -c 20000 /dev/zero\n",
        )
        .unwrap();
        fs::set_permissions(&script, fs::Permissions::from_mode(0o700)).unwrap();
        let mut errors = Vec::new();
        let started = Instant::now();
        let result = gpu(&script, &mut errors);
        assert_eq!(result["availability"], "source_truncated");
        assert!(started.elapsed() < GPU_TIMEOUT);
        assert!(
            errors
                .iter()
                .any(|error| error["code"] == "source_truncated")
        );
    }
    fn p(pid: u32, start: u64, user: u64, rss: u64) -> Proc {
        Proc {
            pid,
            ppid: 1,
            state: ProcState::Running,
            start,
            name: "test".into(),
            user,
            system: 0,
            rss,
            read: Some(user),
            write: Some(0),
            uid: Some(1000),
            service: None,
        }
    }
    #[test]
    fn pid_reuse_is_not_a_cpu_or_io_delta() {
        let old = p(7, 10, 100, 100);
        let new = p(7, 11, 200, 200);
        let previous = HashMap::from([((old.pid, old.start), old)]);
        let rows = leaders(&[new], &previous);
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0]["leader_reasons"], json!(["rss"]));
    }
    #[test]
    fn ppid_uses_stat_field_four_and_is_serialized() {
        let fields = ["S", "17", "1", "2"];
        assert_eq!(parse_ppid(&fields), Some(17));
        assert_eq!(p(42, 7, 0, 1).value(Vec::new())["ppid"], 1);
    }
    #[test]
    fn process_state_is_bounded_and_never_invents_exited() {
        assert_eq!(ProcState::from_code(Some("R")).label(), "running");
        assert_eq!(ProcState::from_code(Some("S")).label(), "sleeping");
        assert_eq!(ProcState::from_code(Some("Z")).label(), "zombie");
        assert_eq!(ProcState::from_code(Some("X")).label(), "dead");
        assert_eq!(
            ProcState::from_code(Some("unrecognized")).label(),
            "unknown"
        );
        assert_eq!(ProcState::from_code(Some("unrecognized")).code(), "?");
        assert_eq!(p(42, 7, 0, 1).value(Vec::new())["state"], "running");
    }
    #[test]
    fn denied_process_io_keeps_valid_stat_row_and_separate_coverage() {
        let mut fields = vec!["0"; 22];
        fields[0] = "S";
        fields[1] = "1";
        fields[11] = "10";
        fields[12] = "2";
        fields[19] = "77";
        fields[21] = "3";
        let stat = format!("42 (fixture) {}", fields.join(" "));
        let mut errors = Vec::new();
        let (row, io_denied) = process_from_stat(
            42,
            &stat,
            100,
            4096,
            Err(io::Error::from(io::ErrorKind::PermissionDenied)),
            Some(1000),
            None,
            &mut errors,
        )
        .unwrap();
        let mut counts = ProcessCounts {
            seen: 1,
            ..ProcessCounts::default()
        };
        counts.io_denied += u64::from(io_denied);
        assert_eq!(row.pid, 42);
        assert_eq!(row.start, 77);
        assert_eq!(row.rss, 3 * 4096);
        assert_eq!(row.read, None);
        assert_eq!(row.write, None);
        assert_eq!(counts.stat_denied, 0);
        assert_eq!(counts.io_denied, 1);
        assert!(
            errors
                .iter()
                .any(|e| { e["source"] == "/proc/*/io" && e["code"] == "permission_denied" })
        );
    }
    #[test]
    fn network_source_tracks_sorted_non_loopback_interface_set() {
        let line = |name: &str, rx: u64, tx: u64| {
            format!("{name}: {rx} 0 0 0 0 0 0 0 {tx} 0 0 0 0 0 0 0\n")
        };
        let header = "Inter-| Receive | Transmit\n face | bytes | bytes\n";
        let first = format!(
            "{header}{}{}{}",
            line("eth1", 10, 20),
            line("lo", 999, 999),
            line("eth0", 5, 7)
        );
        let reordered = format!("{header}{}{}", line("eth0", 50, 70), line("eth1", 100, 200));
        let changed = format!("{header}{}", line("eth0", 50, 70));
        let mut errors = Vec::new();
        let (rx, tx, source, members) = net_counters(&first, &mut errors, |name| Some(name.into()));
        assert_eq!((rx, tx), (json!(15), json!(27)));
        assert_eq!(source, "net:[\"eth0\",\"eth1\"]");
        assert_eq!(members["eth0"], json!([5, 7, "eth0"]));
        assert_eq!(
            source,
            net_counters(&reordered, &mut errors, |name| Some(name.into())).2
        );
        assert_ne!(
            source,
            net_counters(&changed, &mut errors, |name| Some(name.into())).2
        );
        assert!(errors.is_empty());
    }
    #[test]
    fn disk_source_tracks_only_matched_whole_device_set() {
        let line = |name: &str, read: u64, write: u64| {
            format!("8 0 {name} 1 2 {read} 4 5 6 {write} 8 9 10\n")
        };
        let blocks = HashSet::from(["sda".to_owned(), "sdb".to_owned()]);
        let first = format!(
            "{}{}{}",
            line("sdb", 3, 4),
            line("loop0", 99, 99),
            line("sda", 1, 2)
        );
        let reordered = format!("{}{}", line("sda", 10, 20), line("sdb", 30, 40));
        let changed = line("sda", 10, 20);
        let mut errors = Vec::new();
        let (read, write, source, members) =
            disk_counters(&first, &blocks, &mut errors, |name| Some(name.into()));
        assert_eq!((read, write), (json!(4 * 512), json!(6 * 512)));
        assert_eq!(source, "disk:[\"sda\",\"sdb\"]");
        assert_eq!(members["sda"], json!([512, 1024, "sda"]));
        assert_eq!(
            source,
            disk_counters(&reordered, &blocks, &mut errors, |name| Some(name.into())).2
        );
        assert_ne!(
            source,
            disk_counters(&changed, &blocks, &mut errors, |name| Some(name.into())).2
        );
        assert!(errors.is_empty());
    }
    #[test]
    fn disk_instance_detects_replacement_with_same_major_minor() {
        assert_eq!(
            disk_instance(Some("8:0\n"), Some("9\n")),
            Some("8:0@9".into())
        );
        assert_ne!(
            disk_instance(Some("8:0"), Some("9")),
            disk_instance(Some("8:0"), Some("10"))
        );
        assert_eq!(disk_instance(Some("8:0"), None), Some("8:0".into()));
        assert_eq!(
            disk_instance(Some("8:0"), Some("unavailable")),
            Some("8:0".into())
        );
        assert_eq!(disk_instance(None, Some("10")), None);
    }
    #[test]
    fn missing_process_is_not_reported_as_zero() {
        let old = p(7, 10, 100, 100);
        assert!(leaders(&[], &HashMap::from([((old.pid, old.start), old)])).is_empty());
    }
    #[test]
    fn cgroup_service_requires_exact_managed_component() {
        let services = vec!["summitflow-backend.service".to_owned()];
        assert_eq!(
            service_from_cgroup("0::/user.slice/summitflow-backend.service/app", &services)
                .as_deref(),
            Some("summitflow-backend.service")
        );
        assert_eq!(
            service_from_cgroup(
                "0::/user.slice/other-summitflow-backend.service/app",
                &services
            ),
            None
        );
    }
    #[test]
    fn passwd_mapping_is_numeric_and_bounded_to_local_file() {
        let users = parse_passwd(
            "root:x:0:0:root:/root:/bin/sh\nowner:x:1000:1000::/home/owner:/bin/sh\ninvalid:x:nope:1::/:/bin/sh\n",
        );
        assert_eq!(users.get(&1000).map(String::as_str), Some("owner"));
        assert!(!users.contains_key(&1));
    }
}
