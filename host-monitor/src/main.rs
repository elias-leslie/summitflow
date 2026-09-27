mod provider;
mod store;

use chrono::Utc;
use provider::{Proc, ProcessCounts};
use serde_json::{Value, json};
use std::{
    collections::{HashMap, HashSet, VecDeque},
    env, fs,
    io::{self, BufRead, BufReader, Read, Write},
    net::{SocketAddr, TcpStream},
    os::unix::{
        fs::PermissionsExt,
        net::{UnixListener, UnixStream},
    },
    path::{Path, PathBuf},
    process::{Command, Stdio},
    sync::atomic::{AtomicBool, AtomicUsize, Ordering},
    sync::mpsc::{self, Receiver, SyncSender, TryRecvError},
    sync::{Arc, Mutex},
    thread,
    time::{Duration, Instant},
};
use sysinfo::System;

const BASELINE: Duration = Duration::from_secs(5);
const LEADERS: Duration = Duration::from_secs(15);
const GPU_INTERVAL: Duration = Duration::from_secs(15);
const GPU_IDLE_STATUS_INTERVAL: Duration = Duration::from_secs(60 * 60);
const MAX_CONTROL_BYTES: u64 = 4096;
const MAX_ACTIVE_LEASES: usize = 16;
const OBSERVE_TIMEOUT: Duration = Duration::from_secs(7);
const MAX_OBSERVE_BYTES: u64 = 64 * 1024;
const MAX_OBSERVE_RESPONSE: usize = 70 * 1024;
static STOP: AtomicBool = AtomicBool::new(false);
extern "C" fn stop_signal(_: libc::c_int) {
    STOP.store(true, Ordering::Relaxed);
}

struct Config {
    state: PathBuf,
    identity: PathBuf,
    policy: PathBuf,
    samples: Option<u64>,
    interval: Duration,
    gpu_enabled: bool,
    owner_uid: u32,
    owner_gid: u32,
    observe_helper: Option<PathBuf>,
}
impl Config {
    fn parse() -> Result<Self, String> {
        let default_state = env::var_os("SUMMITFLOW_MONITOR_STATE_DIR")
            .map(PathBuf::from)
            .or_else(|| {
                env::var_os("HOME")
                    .map(|h| PathBuf::from(h).join(".local/state/summitflow/monitor"))
            })
            .ok_or("SUMMITFLOW_MONITOR_STATE_DIR and HOME are unset")?;
        let mut state = default_state;
        let mut identity = PathBuf::from("project.identity.json");
        let mut policy = None;
        let mut samples = None;
        let mut interval_ms = 1000;
        let mut owner_uid = unsafe { libc::geteuid() };
        let mut owner_gid = unsafe { libc::getegid() };
        let mut observe_helper = None;
        let mut args = env::args().skip(1);
        while let Some(arg) = args.next() {
            match arg.as_str() {
                "--once" => samples = Some(1),
                "--state-dir" => {
                    state = PathBuf::from(args.next().ok_or("--state-dir needs a path")?)
                }
                "--project-identity" => {
                    identity = PathBuf::from(args.next().ok_or("--project-identity needs a path")?)
                }
                "--policy-snapshot" => {
                    policy = Some(PathBuf::from(
                        args.next().ok_or("--policy-snapshot needs a path")?,
                    ))
                }
                "--samples" => {
                    samples = Some(
                        args.next()
                            .ok_or("--samples needs a number")?
                            .parse()
                            .map_err(|_| "invalid samples")?,
                    )
                }
                "--interval-ms" => {
                    interval_ms = args
                        .next()
                        .ok_or("--interval-ms needs a number")?
                        .parse()
                        .map_err(|_| "invalid interval-ms")?
                }
                "--owner-uid" => {
                    owner_uid = args
                        .next()
                        .ok_or("--owner-uid needs a number")?
                        .parse()
                        .map_err(|_| "invalid owner-uid")?
                }
                "--owner-gid" => {
                    owner_gid = args
                        .next()
                        .ok_or("--owner-gid needs a number")?
                        .parse()
                        .map_err(|_| "invalid owner-gid")?
                }
                "--observe-helper" => {
                    observe_helper = Some(PathBuf::from(
                        args.next().ok_or("--observe-helper needs a path")?,
                    ))
                }
                "--help" | "-h" => {
                    println!(
                        "host-monitor [--state-dir DIR] [--project-identity FILE] [--policy-snapshot FILE] [--owner-uid UID] [--owner-gid GID] [--observe-helper ABSOLUTE_FILE] [--once | --samples N] [--interval-ms N]"
                    );
                    std::process::exit(0)
                }
                _ => return Err(format!("unknown argument: {arg}")),
            }
        }
        if samples == Some(0) || interval_ms == 0 {
            return Err("samples and interval must be positive".into());
        }
        if observe_helper
            .as_ref()
            .is_some_and(|path| !path.is_absolute() || !path.is_file())
        {
            return Err("--observe-helper must be an existing absolute file".into());
        }
        if unsafe { libc::geteuid() } != 0
            && (owner_uid != unsafe { libc::geteuid() } || owner_gid != unsafe { libc::getegid() })
        {
            return Err("unprivileged collector cannot select another owner".into());
        }
        let policy = policy.unwrap_or_else(|| state.join("policy.json"));
        let gpu_enabled = match env::var("SUMMITFLOW_MONITOR_GPU") {
            Ok(value) if value == "off" => false,
            Ok(value) if value == "on" => true,
            Ok(_) => return Err("SUMMITFLOW_MONITOR_GPU must be on or off".into()),
            Err(env::VarError::NotPresent) => true,
            Err(env::VarError::NotUnicode(_)) => {
                return Err("SUMMITFLOW_MONITOR_GPU must be on or off".into());
            }
        };
        Ok(Self {
            state,
            identity,
            policy,
            samples,
            interval: Duration::from_millis(interval_ms),
            gpu_enabled,
            owner_uid,
            owner_gid,
            observe_helper,
        })
    }
}

#[derive(Clone)]
struct Policy {
    cpu: f64,
    memory: f64,
    disk: f64,
    free: u64,
}
fn policy(path: &Path) -> Result<Policy, String> {
    let v: Value = serde_json::from_slice(&fs::read(path).map_err(|e| e.to_string())?)
        .map_err(|e| e.to_string())?;
    if v["schema"] != 1 || v["source"] != "runtime_hygiene_common" {
        return Err("policy schema/source invalid".into());
    }
    let pct = |key: &str| -> Result<f64, String> {
        let n = v[key].as_f64().ok_or_else(|| format!("missing {key}"))?;
        if !n.is_finite() || !(0.0..=100.0).contains(&n) {
            return Err(format!("invalid {key}"));
        }
        Ok(n)
    };
    let free = v["disk_critical_free_bytes"]
        .as_u64()
        .ok_or("missing disk_critical_free_bytes")?;
    Ok(Policy {
        cpu: pct("cpu_critical_pct")?,
        memory: pct("memory_critical_pct")?,
        disk: pct("disk_critical_pct")?,
        free,
    })
}

fn service_names(path: &Path) -> Result<(Vec<String>, u16, String), String> {
    let v: Value = serde_json::from_slice(&fs::read(path).map_err(|e| e.to_string())?)
        .map_err(|e| e.to_string())?;
    let s = &v["services"];
    let mut names = Vec::new();
    for key in ["backend", "frontend"] {
        if let Some(n) = s[key].as_str() {
            names.push(n.to_owned());
        }
    }
    for key in ["default_workers", "optional_workers"] {
        if let Some(a) = s[key].as_array() {
            for n in a.iter().filter_map(Value::as_str) {
                names.push(n.to_owned());
            }
        }
    }
    if names.is_empty()
        || names.iter().any(|n| {
            !n.ends_with(".service") || n.len() > 160 || n.contains('/') || n.starts_with('-')
        })
    {
        return Err("invalid service names".into());
    }
    names.sort();
    names.dedup();
    let port = v["runtime"]["backend_port"]
        .as_u64()
        .filter(|p| *p > 0 && *p < 65536)
        .ok_or("missing backend port")? as u16;
    let endpoint = v["runtime"]["health_endpoint"]
        .as_str()
        .filter(|s| s.starts_with('/') && !s.contains('\n') && s.len() < 128)
        .ok_or("invalid health endpoint")?
        .to_owned();
    Ok((names, port, endpoint))
}

fn utc_ns() -> i64 {
    Utc::now().timestamp_nanos_opt().unwrap_or(0)
}
fn mono_ns() -> i64 {
    let mut ts = std::mem::MaybeUninit::<libc::timespec>::uninit();
    if unsafe { libc::clock_gettime(libc::CLOCK_MONOTONIC, ts.as_mut_ptr()) } != 0 {
        return 0;
    }
    let ts = unsafe { ts.assume_init() };
    ts.tv_sec
        .saturating_mul(1_000_000_000)
        .saturating_add(ts.tv_nsec)
}

fn gpu_poll_due(now: Instant, next: &mut Instant, pending: bool) -> bool {
    if pending || now < *next {
        return false;
    }
    let periods = now.duration_since(*next).as_secs() / GPU_INTERVAL.as_secs() + 1;
    *next = if let Ok(periods) = u32::try_from(periods) {
        *next + GPU_INTERVAL * periods
    } else {
        now + GPU_INTERVAL
    };
    true
}
fn gpu_idle_status_due(now: Instant, next: &mut Instant) -> bool {
    if now < *next {
        return false;
    }
    *next = now + GPU_IDLE_STATUS_INTERVAL;
    true
}
fn add_gpu_observation(host: &mut Value, mut reading: Value, observed_at: i64) {
    reading["observed_at_ns"] = json!(observed_at);
    reading["device_identity_scope"] = json!("sample_boot_id+index");
    if reading.get("poll_interval_seconds").is_none() {
        reading["poll_interval_seconds"] = json!(GPU_INTERVAL.as_secs());
    }
    if let Some(object) = host.as_object_mut() {
        object.insert(
            "gpu_max_utilization_pct".into(),
            reading["max_utilization_pct"].clone(),
        );
        object.insert(
            "gpu_memory_used_bytes".into(),
            reading["memory_used_bytes"].clone(),
        );
        object.insert(
            "gpu_memory_total_bytes".into(),
            reading["memory_total_bytes"].clone(),
        );
        object.insert("gpu".into(), reading);
    }
}
fn status_host(host: &Value) -> Value {
    let mut snapshot = host.clone();
    if let Some(object) = snapshot.as_object_mut() {
        object.remove("net_members");
        object.remove("disk_members");
        if let Some(gpu) = object.get_mut("gpu").and_then(Value::as_object_mut) {
            gpu.remove("devices");
        }
    }
    snapshot
}
fn read_id(path: &str) -> Result<String, String> {
    fs::read_to_string(path)
        .map(|s| s.trim().to_owned())
        .map_err(|e| format!("{path}: {e}"))
}

fn command_timeout(mut command: Command, timeout: Duration) -> io::Result<String> {
    let mut child = command
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()?;
    let start = Instant::now();
    loop {
        if let Some(status) = child.try_wait()? {
            let mut s = String::new();
            if let Some(out) = child.stdout.take() {
                out.take(256 * 1024).read_to_string(&mut s)?;
            }
            if !status.success() {
                return Err(io::Error::other("systemctl show failed"));
            }
            return Ok(s);
        }
        if start.elapsed() >= timeout {
            let _ = child.kill();
            let _ = child.wait();
            return Err(io::Error::new(io::ErrorKind::TimedOut, "systemctl timeout"));
        }
        thread::sleep(Duration::from_millis(10));
    }
}
fn services(
    names: &[String],
    owner_uid: u32,
    owner_gid: u32,
    procs: &[Proc],
    procs_at: Option<i64>,
    procs_mono_at: Option<i64>,
    errors: &mut Vec<Value>,
) -> Value {
    let mut cmd = Command::new("systemctl");
    if unsafe { libc::geteuid() } == 0 && owner_uid != 0 {
        use std::os::unix::process::CommandExt;
        cmd.uid(owner_uid).gid(owner_gid);
        cmd.env("XDG_RUNTIME_DIR", format!("/run/user/{owner_uid}"));
        cmd.env(
            "DBUS_SESSION_BUS_ADDRESS",
            format!("unix:path=/run/user/{owner_uid}/bus"),
        );
    }
    cmd.args([
        "--user",
        "show",
        "--no-pager",
        "--property=Id,ActiveState,SubState,ControlGroup,MainPID",
    ]);
    cmd.args(names);
    let output = match command_timeout(cmd, Duration::from_millis(500)) {
        Ok(s) => s,
        Err(e) => {
            errors.push(json!({"source":"systemctl --user show","code":if e.kind()==io::ErrorKind::TimedOut {"timeout"}else{"error"}}));
            let mut unavailable: serde_json::Map<String, Value> = names.iter().map(|name|(name.clone(),json!({"active_state":null,"sub_state":null,"metrics":null,"availability":if e.kind()==io::ErrorKind::TimedOut {"timeout"}else{"error"}}))).collect();
            if unsafe { libc::geteuid() } == 0 {
                add_system_monitor(&mut unavailable, errors);
            }
            return Value::Object(unavailable);
        }
    };
    let mut out = serde_json::Map::new();
    for block in output.split("\n\n") {
        let mut props = HashMap::new();
        for line in block.lines() {
            if let Some((k, v)) = line.split_once('=') {
                props.insert(k, v);
            }
        }
        let Some(id) = props.get("Id").copied() else {
            continue;
        };
        if !names.iter().any(|n| n == id) {
            continue;
        }
        let mut metric = Value::Null;
        if let Some(group) = props
            .get("ControlGroup")
            .filter(|g| g.starts_with('/') && !g.contains(".."))
        {
            let path = Path::new("/sys/fs/cgroup").join(group.trim_start_matches('/'));
            if path.exists() {
                metric = provider::service(&path.to_string_lossy(), errors);
            }
        }
        if metric.is_null() || metric["cpu_usage_usec"].is_null() {
            let pid = props.get("MainPID").and_then(|p| p.parse::<u32>().ok());
            if let Some(p) = pid.and_then(|pid| procs.iter().find(|p| p.pid == pid)) {
                metric = main_pid_fallback(p, procs_at, procs_mono_at);
            }
        }
        out.insert(id.to_owned(),json!({"active_state":props.get("ActiveState"),"sub_state":props.get("SubState"),"main_pid":props.get("MainPID").and_then(|p|p.parse::<u32>().ok()),"metrics":metric}));
    }
    for name in names {
        out.entry(name.clone())
            .or_insert_with(|| json!({"active_state":null,"sub_state":null,"metrics":null}));
    }
    if unsafe { libc::geteuid() } == 0 {
        add_system_monitor(&mut out, errors);
    }
    Value::Object(out)
}

fn add_system_monitor(out: &mut serde_json::Map<String, Value>, errors: &mut Vec<Value>) {
    let mut system = Command::new("systemctl");
    system.args([
        "--system",
        "show",
        "--no-pager",
        "--property=Id,ActiveState,SubState,ControlGroup,MainPID",
        "summitflow-host-monitor.service",
    ]);
    match command_timeout(system, Duration::from_millis(500)) {
        Ok(output) => {
            let props: HashMap<_, _> = output.lines().filter_map(|line| line.split_once('=')).collect();
            let mut metrics = Value::Null;
            if let Some(group) = props.get("ControlGroup").filter(|g| g.starts_with('/') && !g.contains("..")) {
                let path = Path::new("/sys/fs/cgroup").join(group.trim_start_matches('/'));
                if path.exists() { metrics = provider::service(&path.to_string_lossy(), errors); }
            }
            out.insert("summitflow-host-monitor.service".into(), json!({"active_state":props.get("ActiveState"),"sub_state":props.get("SubState"),"main_pid":props.get("MainPID").and_then(|p|p.parse::<u32>().ok()),"scope":"system","metrics":metrics}));
        }
        Err(e) => errors.push(json!({"source":"systemctl --system show","code":if e.kind()==io::ErrorKind::TimedOut {"timeout"} else {"error"}})),
    }
}

fn main_pid_fallback(p: &Proc, at: Option<i64>, mono: Option<i64>) -> Value {
    json!({"source":"main_pid_fallback","observed_at_ns":at,"observed_monotonic_ns":mono,"cpu_usage_usec":p.user.saturating_add(p.system)/1000,"memory_current_bytes":p.rss,"io_read_bytes":p.read,"io_write_bytes":p.write,"pid":p.pid,"start_ticks":p.start})
}

fn probe(port: u16, path: &str) -> Value {
    let address = SocketAddr::from(([127, 0, 0, 1], port));
    let Ok(mut stream) = TcpStream::connect_timeout(&address, Duration::from_millis(100)) else {
        return json!({"availability":"error"});
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(100)));
    let _ = stream.set_write_timeout(Some(Duration::from_millis(100)));
    if write!(stream, "GET {path} HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n").is_err() {
        return json!({"availability":"error"});
    }
    let mut first = [0u8; 128];
    let n = match stream.read(&mut first) {
        Ok(n) if n > 0 => n,
        Ok(_) => return json!({"availability":"error"}),
        Err(e) => {
            return json!({"availability":if e.kind()==io::ErrorKind::TimedOut || e.kind()==io::ErrorKind::WouldBlock {"timeout"}else{"error"}});
        }
    };
    let line = String::from_utf8_lossy(&first[..n]);
    json!({"availability":"ok","healthy":line.starts_with("HTTP/1.") && line.contains(" 200 ")})
}

fn pressure(host: &Value, p: &Policy) -> Option<bool> {
    let cpu = host["cpu_busy_pct"].as_f64();
    let memory = host["memory_total_bytes"]
        .as_f64()
        .zip(host["memory_available_bytes"].as_f64())
        .filter(|(t, _)| *t > 0.0)
        .map(|(t, a)| 100.0 * (t - a) / t);
    let disk = host["disk_total_bytes"]
        .as_f64()
        .zip(host["disk_free_bytes"].as_f64())
        .filter(|(t, _)| *t > 0.0)
        .map(|(t, f)| 100.0 * (t - f) / t);
    let free = host["disk_free_bytes"].as_u64();
    if cpu.is_some_and(|x| x >= p.cpu)
        || memory.is_some_and(|x| x >= p.memory)
        || disk.is_some_and(|x| x >= p.disk)
        || free.is_some_and(|x| x <= p.free)
    {
        return Some(true);
    }
    if cpu.is_none() || memory.is_none() || disk.is_none() || free.is_none() {
        return None;
    }
    Some(false)
}

struct Runtime {
    leases: HashMap<String, Instant>,
    writer_failure: Option<String>,
    event_failure: Option<String>,
    latest: Option<Value>,
    policy_error: Option<String>,
    trigger_until: Option<Instant>,
    pressure_high: u8,
    pressure_low: u8,
    service_states: HashMap<String, String>,
    source_failures: HashSet<String>,
    sample_commit_ns: VecDeque<u64>,
    sample_commit_total: u64,
}
impl Runtime {
    fn new(policy_error: Option<String>) -> Self {
        Self {
            leases: HashMap::new(),
            writer_failure: None,
            event_failure: None,
            latest: None,
            policy_error,
            trigger_until: None,
            pressure_high: 0,
            pressure_low: 0,
            service_states: HashMap::new(),
            source_failures: HashSet::new(),
            sample_commit_ns: VecDeque::new(),
            sample_commit_total: 0,
        }
    }
    fn record_sample_commit(&mut self, duration_ns: u64) {
        self.sample_commit_total = self.sample_commit_total.saturating_add(1);
        self.sample_commit_ns.push_back(duration_ns);
        if self.sample_commit_ns.len() > 256 {
            self.sample_commit_ns.pop_front();
        }
    }
    fn detail(&mut self, now: Instant) -> bool {
        self.leases.retain(|_, until| *until > now);
        !self.leases.is_empty() || self.trigger_until.is_some_and(|t| t > now)
    }
    fn event(
        &mut self,
        store: &store::Store,
        at: i64,
        kind: &str,
        severity: &str,
        entity: Option<&str>,
        details: &Value,
    ) {
        match store.event(at, kind, severity, entity, details) {
            Ok(()) => self.event_failure = None,
            Err(e) => {
                self.event_failure = Some(e.to_string());
                eprintln!("monitor event write failed: {e}");
            }
        }
    }
    fn dispatch(&mut self, v: &Value, bytes: u64) -> Value {
        let now = Instant::now();
        self.detail(now);
        match v["command"].as_str().unwrap_or("") {
            "status" => {
                let mut durations = self.sample_commit_ns.iter().copied().collect::<Vec<_>>();
                durations.sort_unstable();
                let p95 = if durations.is_empty() {
                    None
                } else {
                    Some(
                        durations
                            [((durations.len() as f64 * 0.95).ceil() as usize).saturating_sub(1)],
                    )
                };
                json!({"ok":true,"schema":1,"collector_version":env!("CARGO_PKG_VERSION"),"detail_active":self.detail(now),"active_leases":self.leases.len(),"max_active_leases":MAX_ACTIVE_LEASES,"writer_failure":self.writer_failure.as_ref().or(self.event_failure.as_ref()),"policy_error":self.policy_error,"latest":self.latest,"storage_bytes":bytes,"sample_commit_p95_ns":p95,"sample_commit_last_ns":self.sample_commit_ns.back(),"sample_commit_count":self.sample_commit_ns.len(),"sample_commit_total":self.sample_commit_total})
            }
            "lease_start" => {
                if self.leases.len() >= MAX_ACTIVE_LEASES {
                    return json!({"ok":false,"error":"lease_capacity_reached","active_leases":self.leases.len(),"max_active_leases":MAX_ACTIVE_LEASES});
                }
                let ttl = v["ttl_seconds"].as_u64().unwrap_or(30).clamp(1, 300);
                let mut id = [0u8; 16];
                if fs::File::open("/dev/urandom")
                    .and_then(|mut f| f.read_exact(&mut id))
                    .is_err()
                {
                    return json!({"ok":false,"error":"random_unavailable"});
                }
                let id = id.iter().map(|b| format!("{b:02x}")).collect::<String>();
                self.leases
                    .insert(id.clone(), now + Duration::from_secs(ttl));
                json!({"ok":true,"lease_id":id,"expires_in_seconds":ttl})
            }
            "lease_renew" => {
                let Some(id) = v["lease_id"].as_str() else {
                    return json!({"ok":false,"error":"missing_lease_id"});
                };
                let Some(expiry) = self.leases.get_mut(id) else {
                    return json!({"ok":false,"error":"unknown_or_expired_lease"});
                };
                let ttl = v["ttl_seconds"].as_u64().unwrap_or(30).clamp(1, 300);
                *expiry = now + Duration::from_secs(ttl);
                json!({"ok":true,"expires_in_seconds":ttl})
            }
            "lease_end" => {
                let Some(id) = v["lease_id"].as_str() else {
                    return json!({"ok":false,"error":"missing_lease_id"});
                };
                json!({"ok":self.leases.remove(id).is_some()})
            }
            _ => json!({"ok":false,"error":"unknown_command"}),
        }
    }
}

fn socket(state: &Path, shared: bool, owner_gid: u32) -> io::Result<UnixListener> {
    let path = state.join("control.sock");
    if path.exists() {
        fs::remove_file(&path)?;
    }
    let listener = UnixListener::bind(&path)?;
    if shared {
        set_group(&path, owner_gid)?;
    }
    fs::set_permissions(
        &path,
        fs::Permissions::from_mode(if shared { 0o660 } else { 0o600 }),
    )?;
    listener.set_nonblocking(true)?;
    Ok(listener)
}

fn set_group(path: &Path, gid: u32) -> io::Result<()> {
    let c = std::ffi::CString::new(path.as_os_str().as_encoded_bytes())?;
    if unsafe { libc::chown(c.as_ptr(), 0, gid) } != 0 {
        return Err(io::Error::last_os_error());
    }
    Ok(())
}

type Mutation = (Value, mpsc::Sender<Value>);

fn peer_is_owner(stream: &UnixStream, owner_uid: u32) -> bool {
    let mut cred = std::mem::MaybeUninit::<libc::ucred>::uninit();
    let mut size = std::mem::size_of::<libc::ucred>() as libc::socklen_t;
    let success = unsafe {
        libc::getsockopt(
            std::os::fd::AsRawFd::as_raw_fd(stream),
            libc::SOL_SOCKET,
            libc::SO_PEERCRED,
            cred.as_mut_ptr().cast(),
            &mut size,
        )
    } == 0;
    success
        && size as usize == std::mem::size_of::<libc::ucred>()
        && unsafe { cred.assume_init() }.uid == owner_uid
}

fn observe_request(v: &Value) -> Result<(), &'static str> {
    if v["schema"] != 1 || v["command"] != "observe" {
        return Err("invalid_request");
    }
    if !matches!(
        v["source"].as_str(),
        Some("logs" | "connections" | "disk_space")
    ) {
        return Err("invalid_source");
    }
    if !v["params"].is_object()
        || v.as_object().is_none_or(|o| {
            o.keys().any(|key| {
                !matches!(
                    key.as_str(),
                    "schema" | "command" | "source" | "params" | "limit" | "max_bytes"
                )
            })
        })
    {
        return Err("invalid_request");
    }
    if !v["limit"].as_u64().is_some_and(|n| (1..=100).contains(&n))
        || !v["max_bytes"]
            .as_u64()
            .is_some_and(|n| (256..=MAX_OBSERVE_BYTES).contains(&n))
    {
        return Err("invalid_limits");
    }
    Ok(())
}

fn observe(helper: &Path, request: &Value, owner_uid: u32) -> Value {
    let mut child = match Command::new(helper)
        .env("SUMMITFLOW_MONITOR_OWNER_UID", owner_uid.to_string())
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
    {
        Ok(child) => child,
        Err(_) => return json!({"schema":1,"ok":false,"error":"helper_unavailable"}),
    };
    let input = format!("{request}\n");
    if child
        .stdin
        .take()
        .is_none_or(|mut input_pipe| input_pipe.write_all(input.as_bytes()).is_err())
    {
        let _ = child.kill();
        let _ = child.wait();
        return json!({"schema":1,"ok":false,"error":"helper_io_error"});
    }
    let mut stdout = child.stdout.take().expect("piped stdout");
    let fd = std::os::fd::AsRawFd::as_raw_fd(&stdout);
    let flags = unsafe { libc::fcntl(fd, libc::F_GETFL) };
    if flags < 0 || unsafe { libc::fcntl(fd, libc::F_SETFL, flags | libc::O_NONBLOCK) } < 0 {
        let _ = child.kill();
        let _ = child.wait();
        return json!({"schema":1,"ok":false,"error":"helper_io_error"});
    }
    let started = Instant::now();
    let mut output = Vec::new();
    let result = loop {
        let mut chunk = [0u8; 4096];
        match stdout.read(&mut chunk) {
            Ok(0) => {}
            Ok(n) => output.extend_from_slice(&chunk[..n]),
            Err(e) if e.kind() == io::ErrorKind::WouldBlock => {}
            Err(_) => break Err("helper_io_error"),
        }
        if output.len() > MAX_OBSERVE_RESPONSE {
            break Err("helper_output_too_large");
        }
        match child.try_wait() {
            Ok(Some(status)) => {
                if !status.success() {
                    break Err("helper_failed");
                }
                // The helper writes a single JSON line; allow the pipe to settle after exit.
                let mut rest = Vec::new();
                if stdout.read_to_end(&mut rest).is_err() {
                    break Err("helper_io_error");
                }
                output.extend(rest);
                if output.len() > MAX_OBSERVE_RESPONSE {
                    break Err("helper_output_too_large");
                }
                break Ok(());
            }
            Ok(None) if started.elapsed() < OBSERVE_TIMEOUT => {
                thread::sleep(Duration::from_millis(10))
            }
            Ok(None) => break Err("helper_timeout"),
            Err(_) => break Err("helper_io_error"),
        }
    };
    if let Err(code) = result {
        let _ = child.kill();
        let _ = child.wait();
        return json!({"schema":1,"ok":false,"error":code});
    }
    let Ok(value) = serde_json::from_slice::<Value>(&output) else {
        return json!({"schema":1,"ok":false,"error":"helper_invalid_json"});
    };
    if value["schema"] != 1
        || !value["items"].is_array()
        || !value["errors"].is_array()
        || !value["coverage"].is_object()
    {
        return json!({"schema":1,"ok":false,"error":"helper_invalid_result"});
    }
    if serde_json::to_vec(&value)
        .is_ok_and(|bytes| bytes.len() > request["max_bytes"].as_u64().unwrap_or(0) as usize)
    {
        return json!({"schema":1,"ok":false,"error":"helper_output_too_large"});
    }
    json!({"schema":1,"ok":true,"result":value})
}

fn control_request(
    mut stream: UnixStream,
    owner_uid: u32,
    snapshot: &Arc<Mutex<Value>>,
    mutations: &SyncSender<Mutation>,
    helper: Option<&Path>,
    active: &Arc<AtomicUsize>,
) -> io::Result<()> {
    stream.set_read_timeout(Some(Duration::from_millis(300)))?;
    stream.set_write_timeout(Some(Duration::from_secs(1)))?;
    if !peer_is_owner(&stream, owner_uid) {
        return Ok(());
    }
    let mut line = String::new();
    let n = BufReader::new(&stream)
        .take(MAX_CONTROL_BYTES + 1)
        .read_line(&mut line)?;
    let response = if n as u64 > MAX_CONTROL_BYTES {
        json!({"ok":false,"error":"request_too_large"})
    } else if let Ok(v) = serde_json::from_str::<Value>(&line) {
        match v["command"].as_str() {
            Some("status") => snapshot
                .lock()
                .map(|v| v.clone())
                .unwrap_or_else(|_| json!({"ok":false,"error":"status_unavailable"})),
            Some("observe") => {
                if let Err(code) = observe_request(&v) {
                    json!({"schema":1,"ok":false,"error":code})
                } else if let Some(helper) = helper {
                    if active
                        .fetch_update(Ordering::AcqRel, Ordering::Acquire, |n| {
                            (n < 2).then_some(n + 1)
                        })
                        .is_err()
                    {
                        json!({"schema":1,"ok":false,"error":"observe_busy"})
                    } else {
                        let result = observe(helper, &v, owner_uid);
                        active.fetch_sub(1, Ordering::AcqRel);
                        result
                    }
                } else {
                    json!({"schema":1,"ok":false,"error":"helper_unavailable"})
                }
            }
            Some("lease_start" | "lease_renew" | "lease_end") => {
                let (tx, rx) = mpsc::channel();
                if mutations.try_send((v, tx)).is_err() {
                    json!({"ok":false,"error":"control_busy"})
                } else {
                    rx.recv_timeout(Duration::from_secs(2))
                        .unwrap_or_else(|_| json!({"ok":false,"error":"control_timeout"}))
                }
            }
            _ => json!({"ok":false,"error":"unknown_command"}),
        }
    } else {
        json!({"ok":false,"error":"invalid_json"})
    };
    writeln!(stream, "{response}")
}

fn control_loop(
    listener: UnixListener,
    owner_uid: u32,
    snapshot: Arc<Mutex<Value>>,
    mutations: SyncSender<Mutation>,
    helper: Option<PathBuf>,
) {
    let active = Arc::new(AtomicUsize::new(0));
    let clients = Arc::new(AtomicUsize::new(0));
    while !STOP.load(Ordering::Relaxed) {
        match listener.accept() {
            Ok((stream, _)) => {
                let snapshot = Arc::clone(&snapshot);
                let mutations = mutations.clone();
                let helper = helper.clone();
                let active = Arc::clone(&active);
                if clients
                    .fetch_update(Ordering::AcqRel, Ordering::Acquire, |n| {
                        (n < 8).then_some(n + 1)
                    })
                    .is_err()
                {
                    continue;
                }
                let clients = Arc::clone(&clients);
                thread::spawn(move || {
                    let _ = control_request(
                        stream,
                        owner_uid,
                        &snapshot,
                        &mutations,
                        helper.as_deref(),
                        &active,
                    );
                    clients.fetch_sub(1, Ordering::AcqRel);
                });
            }
            Err(e) if e.kind() == io::ErrorKind::WouldBlock => {
                thread::sleep(Duration::from_millis(10))
            }
            Err(_) => thread::sleep(Duration::from_millis(50)),
        }
    }
}

struct PersistResult {
    baseline_committed: bool,
    failure: Option<String>,
}

fn persist_pair(
    store: &mut store::Store,
    baseline: &store::Sample<'_>,
    detail: Option<&store::Sample<'_>>,
) -> PersistResult {
    if let Err(e) = store.write(baseline) {
        return PersistResult {
            baseline_committed: false,
            failure: Some(format!("baseline write failed: {e}")),
        };
    }
    if let Some(detail) = detail {
        if let Err(e) = store.write(detail) {
            return PersistResult {
                baseline_committed: true,
                failure: Some(format!("detail write failed; baseline committed: {e}")),
            };
        }
    }
    PersistResult {
        baseline_committed: true,
        failure: None,
    }
}

fn run(cfg: Config) -> Result<(), Box<dyn std::error::Error>> {
    unsafe {
        libc::signal(
            libc::SIGTERM,
            stop_signal as *const () as libc::sighandler_t,
        );
        libc::signal(libc::SIGINT, stop_signal as *const () as libc::sighandler_t);
    }
    let (names, port, endpoint) = service_names(&cfg.identity)?;
    let boot = read_id("/proc/sys/kernel/random/boot_id")?;
    let host = read_id("/etc/machine-id").unwrap_or_else(|_| "unknown".into());
    fs::create_dir_all(&cfg.state)?;
    let shared = unsafe { libc::geteuid() } == 0 && cfg.owner_uid != 0;
    if shared {
        unsafe { libc::umask(0o027) };
    }
    if shared {
        set_group(&cfg.state, cfg.owner_gid)?;
    }
    fs::set_permissions(
        &cfg.state,
        fs::Permissions::from_mode(if shared { 0o750 } else { 0o700 }),
    )?;
    let lock_path = cfg.state.join("collector.lock");
    let lock = fs::OpenOptions::new()
        .create(true)
        .write(true)
        .open(&lock_path)?;
    if shared {
        set_group(&lock_path, cfg.owner_gid)?;
    }
    fs::set_permissions(
        &lock_path,
        fs::Permissions::from_mode(if shared { 0o640 } else { 0o600 }),
    )?;
    if unsafe {
        libc::flock(
            std::os::fd::AsRawFd::as_raw_fd(&lock),
            libc::LOCK_EX | libc::LOCK_NB,
        )
    } != 0
    {
        return Err("collector already running".into());
    }
    let mut store =
        store::Store::open_with_owner(&cfg.state, &host, &boot, shared.then_some(cfg.owner_gid))?;
    let listener = socket(&cfg.state, shared, cfg.owner_gid)?;
    let pol = policy(&cfg.policy);
    let mut state = Runtime::new(pol.as_ref().err().cloned());
    let snapshot = Arc::new(Mutex::new(
        state.dispatch(&json!({"command":"status"}), store.bytes()),
    ));
    let (mutation_tx, mutation_rx) = mpsc::sync_channel::<Mutation>(32);
    let control_snapshot = Arc::clone(&snapshot);
    let control_helper = cfg.observe_helper.clone();
    let owner_uid = cfg.owner_uid;
    let control_worker = thread::spawn(move || {
        control_loop(
            listener,
            owner_uid,
            control_snapshot,
            mutation_tx,
            control_helper,
        )
    });
    state.event(
        &store,
        utc_ns(),
        "collector_restart",
        "info",
        None,
        &json!({"version":env!("CARGO_PKG_VERSION")}),
    );
    if let Some(reason) = state.policy_error.clone() {
        state.event(
            &store,
            utc_ns(),
            "source_failure",
            "warning",
            Some("policy_snapshot"),
            &json!({"code":"unavailable","reason":reason}),
        );
    }
    let mut sys = System::new();
    let mut cpu_prev = None;
    let mut proc_prev = HashMap::new();
    let mut latest_procs = Vec::new();
    let mut last_prune = None;
    let mut cached_leaders = Vec::new();
    let mut leader_scan_at = None;
    let mut leader_scan_mono = None;
    let mut cached_scan_stats = ProcessCounts::default();
    let mut cached_services = json!({});
    let mut was_detail = false;
    let mut probe_rx: Option<Receiver<(i64, Value)>> = None;
    let mut last_health = json!({"availability":"not_collected"});
    let mut gpu_rx: Option<Receiver<(i64, Value, Vec<Value>)>> = None;
    let mut gpu_worker: Option<thread::JoinHandle<()>> = None;
    let mut gpu_available = Path::new("/usr/bin/nvidia-smi").is_file();
    let mut iterations = 0u64;
    let mut target = Instant::now();
    let mut next_baseline = target;
    let mut next_leaders = target;
    let mut next_gpu = target;
    let mut next_gpu_idle_status = target;
    'run: loop {
        let now = Instant::now();
        for (request, reply) in mutation_rx.try_iter().take(32) {
            let _ = reply.send(state.dispatch(&request, store.bytes()));
        }
        let detail = state.detail(now);
        let baseline_due = now >= next_baseline;
        let leaders_due = now >= next_leaders;
        if baseline_due || detail {
            let started = Instant::now();
            let at = utc_ns();
            let mono = mono_ns();
            let mut errors = Vec::new();
            let (mut host_data, new_cpu) = provider::host(&mut sys, cpu_prev, &mut errors);
            cpu_prev = new_cpu;
            if baseline_due {
                if (!cfg.gpu_enabled || !gpu_available)
                    && gpu_idle_status_due(now, &mut next_gpu_idle_status)
                {
                    // A one-time disabled/unsupported sample ages out of raw history.
                    // Recheck an absent executable and retain a bounded status record
                    // without starting a subprocess or a separate transaction.
                    if cfg.gpu_enabled {
                        gpu_available = Path::new("/usr/bin/nvidia-smi").is_file();
                    }
                    if !cfg.gpu_enabled || !gpu_available {
                        let mut reading = provider::gpu_unavailable(if cfg.gpu_enabled {
                            "unsupported"
                        } else {
                            "disabled"
                        });
                        reading["poll_interval_seconds"] = Value::Null;
                        reading["status_refresh_seconds"] =
                            json!(GPU_IDLE_STATUS_INTERVAL.as_secs());
                        add_gpu_observation(&mut host_data, reading, at);
                    } else {
                        next_gpu = now;
                    }
                }
                if let Some(rx) = &gpu_rx {
                    match rx.try_recv() {
                        Ok((observed_at, reading, gpu_errors)) => {
                            add_gpu_observation(&mut host_data, reading, observed_at);
                            errors.extend(gpu_errors);
                            gpu_rx = None;
                            if let Some(worker) = gpu_worker.take() {
                                let _ = worker.join();
                            }
                        }
                        Err(TryRecvError::Disconnected) => {
                            errors
                                .push(json!({"source":"nvidia-smi","code":"worker_disconnected"}));
                            add_gpu_observation(
                                &mut host_data,
                                provider::gpu_unavailable("error"),
                                at,
                            );
                            gpu_rx = None;
                            if let Some(worker) = gpu_worker.take() {
                                let _ = worker.join();
                            }
                        }
                        Err(TryRecvError::Empty) => {}
                    }
                }
                if cfg.gpu_enabled
                    && gpu_available
                    && gpu_poll_due(now, &mut next_gpu, gpu_rx.is_some())
                {
                    let (tx, rx) = mpsc::channel();
                    gpu_worker = Some(thread::spawn(move || {
                        let mut errors = Vec::new();
                        let reading = provider::gpu(Path::new("/usr/bin/nvidia-smi"), &mut errors);
                        let _ = tx.send((utc_ns(), reading, errors));
                    }));
                    gpu_rx = Some(rx);
                }
            }
            let mut scan = detail || leaders_due;
            let mut scan_counts = if scan {
                let (procs, counts) = provider::processes(&mut errors, &names);
                latest_procs = procs;
                counts
            } else {
                cached_scan_stats
            };
            let mut service_data = if baseline_due {
                services(
                    &names,
                    cfg.owner_uid,
                    cfg.owner_gid,
                    &latest_procs,
                    if scan { Some(at) } else { leader_scan_at },
                    if scan { Some(mono) } else { leader_scan_mono },
                    &mut errors,
                )
            } else {
                cached_services.clone()
            };
            if baseline_due {
                if let Some(rx) = &probe_rx {
                    match rx.try_recv() {
                        Ok((probe_at, mut result)) => {
                            result["observed_at_ns"] = json!(probe_at);
                            last_health = result;
                            probe_rx = None;
                        }
                        Err(TryRecvError::Disconnected) => {
                            probe_rx = None;
                            last_health = json!({"availability":"error"});
                        }
                        Err(TryRecvError::Empty) => {}
                    }
                }
                if probe_rx.is_none() {
                    let (tx, rx) = mpsc::channel();
                    let path = endpoint.clone();
                    thread::spawn(move || {
                        let _ = tx.send((utc_ns(), probe(port, &path)));
                    });
                    probe_rx = Some(rx);
                }
                if let Some(object) = service_data.as_object_mut() {
                    object.insert("backend_health".into(), last_health.clone());
                    for value in object.values_mut() {
                        if let Some(item) = value.as_object_mut() {
                            if !item.contains_key("observed_at_ns") {
                                item.insert("observed_at_ns".into(), json!(at));
                            }
                        }
                    }
                }
                cached_services = service_data.clone();
                if let Some(object) = service_data.as_object() {
                    for name in &names {
                        let current = object
                            .get(name)
                            .and_then(|v| v["active_state"].as_str())
                            .unwrap_or("unavailable")
                            .to_owned();
                        if let Some(old) =
                            state.service_states.insert(name.clone(), current.clone())
                        {
                            if old != current {
                                state.event(
                                    &store,
                                    at,
                                    "service_state_change",
                                    "info",
                                    Some(name),
                                    &json!({"from":old,"to":current}),
                                );
                                if current == "failed" || current == "inactive" {
                                    state.trigger_until = Some(now + Duration::from_secs(60));
                                    state.event(
                                        &store,
                                        at,
                                        "capture_start",
                                        "warning",
                                        Some(name),
                                        &json!({"reason":"service_transition"}),
                                    );
                                }
                            }
                        }
                    }
                }
                if let Ok(p) = &pol {
                    match pressure(&host_data, p) {
                        Some(true) => {
                            state.pressure_high = state.pressure_high.saturating_add(1);
                            state.pressure_low = 0;
                            if state.pressure_high >= 3 {
                                state.trigger_until = Some(now + Duration::from_secs(60));
                                if state.pressure_high == 3 {
                                    state.event(
                                        &store,
                                        at,
                                        "capture_start",
                                        "warning",
                                        None,
                                        &json!({"reason":"high_pressure"}),
                                    );
                                }
                            }
                        }
                        Some(false) => {
                            state.pressure_low = state.pressure_low.saturating_add(1);
                            state.pressure_high = 0;
                            if state.pressure_low >= 3 && state.leases.is_empty() {
                                state.trigger_until = None;
                            }
                        }
                        None => {}
                    }
                }
            }
            let active = state.detail(now);
            if active && !scan {
                let (procs, counts) = provider::processes(&mut errors, &names);
                latest_procs = procs;
                scan_counts = counts;
                scan = true;
            }
            for error in &errors {
                let key = format!(
                    "{}:{}",
                    error["source"].as_str().unwrap_or("unknown"),
                    error["code"].as_str().unwrap_or("error")
                );
                if state.source_failures.insert(key) {
                    state.event(
                        &store,
                        at,
                        "source_failure",
                        "warning",
                        error["source"].as_str(),
                        &json!({"code":error["code"]}),
                    );
                }
            }
            if active && !was_detail {
                let reason = if state.leases.is_empty() {
                    "trigger"
                } else {
                    "lease"
                };
                state.event(
                    &store,
                    at,
                    "capture_start",
                    "info",
                    None,
                    &json!({"reason":reason}),
                );
            } else if !active && was_detail {
                state.event(
                    &store,
                    at,
                    "capture_stop",
                    "info",
                    None,
                    &json!({"reason":"lease_or_trigger_expired"}),
                );
            }
            was_detail = active;
            let mode = if active { "detail" } else { "baseline" };
            if scan {
                cached_leaders = provider::leaders(&latest_procs, &proc_prev);
                for row in &mut cached_leaders {
                    row["observed_at_ns"] = json!(at);
                    row["observed_monotonic_ns"] = json!(mono);
                }
                leader_scan_at = Some(at);
                leader_scan_mono = Some(mono);
                cached_scan_stats = scan_counts;
            }
            if let Some(object) = host_data.as_object_mut() {
                object.insert("leaders_sampled_at_ns".into(), json!(leader_scan_at));
                object.insert(
                    "process_io_permission_denied".into(),
                    json!(scan_counts.io_denied),
                );
                object.insert("process_scan_observed_at_ns".into(), json!(leader_scan_at));
                object.insert(
                    "process_scan_observed_monotonic_ns".into(),
                    json!(leader_scan_mono),
                );
            }
            let detail_rows = if active && baseline_due {
                latest_procs
                    .iter()
                    .map(|p| {
                        let mut row = p.value(Vec::new());
                        row["observed_at_ns"] = json!(at);
                        row["observed_monotonic_ns"] = json!(mono);
                        row
                    })
                    .collect::<Vec<_>>()
            } else {
                Vec::new()
            };
            if scan {
                proc_prev = latest_procs
                    .iter()
                    .map(|p| ((p.pid, p.start), p.clone()))
                    .collect();
                while next_leaders <= now {
                    next_leaders += LEADERS;
                }
            }
            state.latest = Some(
                json!({"sampled_at_ns":at,"monotonic_ns":mono,"mode":mode,"host":status_host(&host_data),"services":service_data,"processes_seen":scan_counts.seen,"processes_permission_denied":scan_counts.stat_denied,"process_io_permission_denied":scan_counts.io_denied,"processes_exited":scan_counts.exited,"process_scan_observed_at_ns":leader_scan_at,"process_scan_observed_monotonic_ns":leader_scan_mono,"errors":errors}),
            );
            if baseline_due {
                let duration_ns = started.elapsed().as_nanos() as u64;
                let baseline = store::Sample {
                    at_ns: at,
                    mono_ns: mono,
                    boot_id: &boot,
                    mode: "baseline",
                    host: &host_data,
                    services: &service_data,
                    processes: &cached_leaders,
                    seen: scan_counts.seen,
                    denied: scan_counts.stat_denied,
                    exited: scan_counts.exited,
                    errors: &errors,
                    duration_ns,
                    reason: None,
                };
                let detail = active.then(|| store::Sample {
                    at_ns: at,
                    mono_ns: mono,
                    boot_id: &boot,
                    mode: "detail",
                    host: &host_data,
                    services: &service_data,
                    processes: &detail_rows,
                    seen: scan_counts.seen,
                    denied: scan_counts.stat_denied,
                    exited: scan_counts.exited,
                    errors: &errors,
                    duration_ns,
                    reason: Some(if state.leases.is_empty() {
                        "trigger"
                    } else {
                        "lease"
                    }),
                });
                let result = persist_pair(&mut store, &baseline, detail.as_ref());
                state.writer_failure = result.failure;
                if let Some(e) = &state.writer_failure {
                    eprintln!("monitor write failed: {e}");
                }
                if result.baseline_committed {
                    state.record_sample_commit(
                        started.elapsed().as_nanos().min(u64::MAX as u128) as u64
                    );
                }
                while next_baseline <= now {
                    next_baseline += BASELINE;
                }
            }
            if let Ok(mut current) = snapshot.lock() {
                *current = state.dispatch(&json!({"command":"status"}), store.bytes());
            }
        }
        if last_prune.is_none_or(|t: Instant| now.duration_since(t) > Duration::from_secs(60)) {
            if let Err(e) = store.prune(utc_ns()) {
                state.writer_failure = Some(e.to_string());
                eprintln!("monitor prune failed: {e}");
            }
            last_prune = Some(now);
        }
        iterations += 1;
        if STOP.load(Ordering::Relaxed) || cfg.samples.is_some_and(|n| iterations >= n) {
            break;
        }
        target += cfg.interval;
        while target <= Instant::now() {
            target += cfg.interval;
        }
        loop {
            if STOP.load(Ordering::Relaxed) {
                break 'run;
            }
            for (request, reply) in mutation_rx.try_iter().take(32) {
                let _ = reply.send(state.dispatch(&request, store.bytes()));
            }
            if let Ok(mut current) = snapshot.lock() {
                *current = state.dispatch(&json!({"command":"status"}), store.bytes());
            }
            let now = Instant::now();
            if now >= target {
                break;
            }
            thread::sleep((target - now).min(Duration::from_millis(100)));
        }
    }
    if let Some(worker) = gpu_worker.take() {
        let _ = worker.join();
    }
    store.flush_rollups()?;
    STOP.store(true, Ordering::Relaxed);
    let _ = control_worker.join();
    let _ = fs::remove_file(cfg.state.join("control.sock"));
    Ok(())
}

fn main() {
    unsafe { libc::umask(0o077) };
    match Config::parse().and_then(|c| run(c).map_err(|e| e.to_string())) {
        Ok(()) => {}
        Err(e) => {
            eprintln!("host-monitor: {e}");
            std::process::exit(1)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn observe_contract_rejects_unbounded_or_untyped_requests() {
        let good = json!({"schema":1,"command":"observe","source":"disk_space","params":{},"limit":10,"max_bytes":4096});
        assert!(observe_request(&good).is_ok());
        let mut bad = good.clone();
        bad["source"] = json!("command");
        assert_eq!(observe_request(&bad), Err("invalid_source"));
        bad = good.clone();
        bad["max_bytes"] = json!(65537);
        assert_eq!(observe_request(&bad), Err("invalid_limits"));
        bad = good.clone();
        bad["params"] = json!(["/"]);
        assert_eq!(observe_request(&bad), Err("invalid_request"));
        bad = good;
        bad["argv"] = json!(["sh"]);
        assert_eq!(observe_request(&bad), Err("invalid_request"));
    }

    #[test]
    fn observe_helper_output_is_wrapped_and_bounded() {
        let dir = tempfile::tempdir().unwrap();
        let script = dir.path().join("helper");
        fs::write(&script, "#!/bin/sh\ncat >/dev/null\nprintf '{\"schema\":1,\"coverage\":{\"owner_uid\":\"%s\"},\"items\":[],\"errors\":[]}\\n' \"$SUMMITFLOW_MONITOR_OWNER_UID\"\n").unwrap();
        fs::set_permissions(&script, fs::Permissions::from_mode(0o700)).unwrap();
        let request = json!({"schema":1,"command":"observe","source":"disk_space","params":{},"limit":10,"max_bytes":4096});
        let response = observe(&script, &request, 42);
        assert_eq!(response["ok"], true);
        assert_eq!(response["result"]["schema"], 1);
        assert_eq!(response["result"]["coverage"]["owner_uid"], "42");
        fs::write(&script, "#!/bin/sh\ncat >/dev/null\nprintf '%s\\n' '[]'\n").unwrap();
        assert_eq!(
            observe(&script, &request, unsafe { libc::geteuid() })["error"],
            "helper_invalid_result"
        );
    }

    #[test]
    fn socket_peer_is_exact_owner_uid() {
        let (left, _right) = UnixStream::pair().unwrap();
        let uid = unsafe { libc::geteuid() };
        assert!(peer_is_owner(&left, uid));
        assert!(!peer_is_owner(&left, uid.wrapping_add(1)));
    }

    #[test]
    fn gpu_poll_schedule_does_not_overlap_or_catch_up_in_a_burst() {
        let started = Instant::now();
        let mut next = started;
        assert!(gpu_poll_due(started, &mut next, false));
        assert!(!gpu_poll_due(
            started + Duration::from_secs(10),
            &mut next,
            false
        ));
        assert!(!gpu_poll_due(
            started + Duration::from_secs(15),
            &mut next,
            true
        ));
        assert!(gpu_poll_due(
            started + Duration::from_secs(45),
            &mut next,
            false
        ));
        assert!(!gpu_poll_due(
            started + Duration::from_secs(45),
            &mut next,
            false
        ));
    }
    #[test]
    fn disabled_or_absent_gpu_status_remains_in_raw_history_after_a_day() {
        let started = Instant::now();
        let mut next = started;
        assert!(gpu_idle_status_due(started, &mut next));
        assert!(!gpu_idle_status_due(
            started + Duration::from_secs(59 * 60),
            &mut next
        ));
        assert!(gpu_idle_status_due(
            started + Duration::from_secs(60 * 60),
            &mut next
        ));
        assert!(gpu_idle_status_due(
            started + Duration::from_secs(25 * 60 * 60),
            &mut next
        ));
    }
    #[test]
    fn gpu_observation_keeps_disabled_distinct_from_sampled_provider() {
        let mut disabled = json!({});
        add_gpu_observation(
            &mut disabled,
            json!({"availability":"disabled","poll_interval_seconds":null}),
            123,
        );
        assert_eq!(disabled["gpu"]["availability"], "disabled");
        assert_eq!(disabled["gpu"]["poll_interval_seconds"], Value::Null);
        assert_eq!(disabled["gpu_max_utilization_pct"], Value::Null);
        let mut sampled = json!({});
        add_gpu_observation(
            &mut sampled,
            json!({"availability":"ok","max_utilization_pct":25.0}),
            456,
        );
        assert_eq!(sampled["gpu"]["poll_interval_seconds"], 15);
        assert_eq!(sampled["gpu"]["observed_at_ns"], 456);
        assert_eq!(sampled["gpu_max_utilization_pct"], 25.0);
    }
    #[test]
    fn socket_status_omits_internal_member_maps_at_provider_limit() {
        let members: serde_json::Map<String, Value> = (0..64)
            .map(|index| (format!("device-{index:02}"), json!([100, 200, "259:0:9"])))
            .collect();
        let gpu_devices: Vec<Value> = (0..32)
            .map(|index| {
                json!({"index":index,"name":"X".repeat(64),"utilization_pct":25.0,"memory_used_bytes":1024,"memory_total_bytes":2048,"temperature_c":45.0,"power_w":100.0})
            })
            .collect();
        let host = json!({"cpu_busy_pct":25,"memory_total_bytes":64_000_000_000u64,"memory_available_bytes":32_000_000_000u64,"net_members":members,"disk_members":members,"gpu":{"provider":"nvidia-smi","availability":"ok","observed_at_ns":123,"poll_interval_seconds":15,"devices_seen":32,"devices_scanned":32,"max_utilization_pct":25.0,"memory_used_bytes":32768,"memory_total_bytes":65536,"devices":gpu_devices}});
        assert!(serde_json::to_vec(&host).unwrap().len() > 8192);
        let public = status_host(&host);
        assert_eq!(host["net_members"].as_object().unwrap().len(), 64);
        assert_eq!(host["disk_members"].as_object().unwrap().len(), 64);
        assert!(public.get("net_members").is_none());
        assert!(public.get("disk_members").is_none());
        assert!(public["gpu"].get("devices").is_none());
        assert_eq!(public["gpu"]["devices_seen"], 32);
        assert_eq!(public["gpu"]["observed_at_ns"], 123);
        let mut runtime = Runtime::new(None);
        runtime.latest = Some(
            json!({"host":public,"services":{"summitflow-backend.service":{"active_state":"active","metrics":{"cpu_usage_usec":1,"memory_current_bytes":2}},"summitflow-frontend.service":{"active_state":"active","metrics":{"cpu_usage_usec":1,"memory_current_bytes":2}},"summitflow-hatchet-worker.service":{"active_state":"active","metrics":{"cpu_usage_usec":1,"memory_current_bytes":2}},"summitflow-host-monitor.service":{"active_state":"active","metrics":{"cpu_usage_usec":1,"memory_current_bytes":2}}},"sampled_at_ns":1,"mode":"baseline"}),
        );
        let response = runtime.dispatch(&json!({"command":"status"}), 0);
        assert!(serde_json::to_vec(&response).unwrap().len() < 8192);
    }
    #[test]
    fn commit_total_continues_after_latency_window_fills() {
        let mut runtime = Runtime::new(None);
        for duration in 1..=260 {
            runtime.record_sample_commit(duration);
        }
        let status = runtime.dispatch(&json!({"command":"status"}), 0);
        assert_eq!(status["sample_commit_count"], 256);
        assert_eq!(status["sample_commit_total"], 260);
        assert_eq!(status["sample_commit_last_ns"], 260);
        assert_eq!(status["sample_commit_p95_ns"], 248);
        runtime.record_sample_commit(261);
        let next = runtime.dispatch(&json!({"command":"status"}), 0);
        assert_eq!(next["sample_commit_count"], 256);
        assert_eq!(next["sample_commit_total"], 261);
        assert_eq!(next["sample_commit_last_ns"], 261);
    }
    #[test]
    fn main_pid_fallback_keeps_process_scan_timestamps() {
        let p = Proc {
            pid: 42,
            ppid: 1,
            state: provider::ProcState::Running,
            start: 7,
            name: "p".into(),
            user: 20_000,
            system: 3_000,
            rss: 4096,
            read: Some(8),
            write: Some(9),
            uid: Some(1000),
            service: None,
        };
        let metric = main_pid_fallback(&p, Some(100), Some(200));
        assert_eq!(metric["observed_at_ns"], 100);
        assert_eq!(metric["observed_monotonic_ns"], 200);
        assert_eq!(metric["cpu_usage_usec"], 23);
    }
    #[test]
    fn detail_write_failure_keeps_separate_baseline() {
        let dir = tempfile::tempdir().unwrap();
        let mut store = store::Store::open(dir.path(), "h", "b").unwrap();
        store.conn.execute_batch("CREATE TRIGGER reject_detail BEFORE INSERT ON samples WHEN NEW.mode='detail' BEGIN SELECT RAISE(FAIL,'detail_fixture'); END;").unwrap();
        let host = json!({"cpu_busy_pct":10});
        let services = json!({});
        let all = [json!({"pid":2}), json!({"pid":3})];
        let leaders = [json!({"pid":2,"leader_reasons":["rss"]})];
        let detail = store::Sample {
            at_ns: 1,
            mono_ns: 1,
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
        let baseline = store::Sample {
            at_ns: 1,
            mono_ns: 1,
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
        let result = persist_pair(&mut store, &baseline, Some(&detail));
        assert!(result.baseline_committed);
        let failure = result.failure.unwrap();
        assert!(failure.contains("baseline committed"));
        let (mode, reason, blob): (String, Option<String>, Vec<u8>) = store
            .conn
            .query_row(
                "SELECT mode,capture_reason,process_blob FROM samples",
                [],
                |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
            )
            .unwrap();
        assert_eq!(mode, "baseline");
        assert_eq!(reason, None);
        let mut decoded = String::new();
        use std::io::Read;
        flate2::read::GzDecoder::new(&blob[..])
            .read_to_string(&mut decoded)
            .unwrap();
        assert_eq!(
            serde_json::from_str::<Value>(&decoded).unwrap(),
            json!(leaders)
        );
    }
    #[test]
    fn rejected_baseline_is_not_counted_as_committed() {
        let dir = tempfile::tempdir().unwrap();
        let mut store = store::Store::open(dir.path(), "h", "b").unwrap();
        store.conn.execute_batch("CREATE TRIGGER reject_baseline BEFORE INSERT ON samples BEGIN SELECT RAISE(FAIL,'baseline_fixture'); END;").unwrap();
        let host = json!({"cpu_busy_pct":10});
        let services = json!({});
        let baseline = store::Sample {
            at_ns: 1,
            mono_ns: 1,
            boot_id: "b",
            mode: "baseline",
            host: &host,
            services: &services,
            processes: &[],
            seen: 0,
            denied: 0,
            exited: 0,
            errors: &[],
            duration_ns: 1,
            reason: None,
        };
        let result = persist_pair(&mut store, &baseline, None);
        assert!(!result.baseline_committed);
        assert!(result.failure.unwrap().contains("baseline write failed"));
    }
    #[test]
    fn lease_expires_and_renews() {
        let mut r = Runtime::new(None);
        let a = r.dispatch(&json!({"command":"lease_start","ttl_seconds":1}), 0);
        let id = a["lease_id"].as_str().unwrap();
        assert!(r.detail(Instant::now()));
        assert_eq!(
            r.dispatch(
                &json!({"command":"lease_renew","lease_id":id,"ttl_seconds":2}),
                0
            )["ok"],
            true
        );
        r.leases
            .insert(id.into(), Instant::now() - Duration::from_secs(1));
        assert!(!r.detail(Instant::now()));
        assert_eq!(
            r.dispatch(&json!({"command":"lease_renew","lease_id":id}), 0)["ok"],
            false
        );
    }
    #[test]
    fn lease_capacity_is_bounded_and_expiry_releases_a_slot() {
        let mut r = Runtime::new(None);
        let mut ids = Vec::new();
        for _ in 0..MAX_ACTIVE_LEASES {
            let response = r.dispatch(&json!({"command":"lease_start","ttl_seconds":300}), 0);
            assert_eq!(response["ok"], true);
            ids.push(response["lease_id"].as_str().unwrap().to_owned());
        }
        assert_eq!(r.leases.len(), MAX_ACTIVE_LEASES);
        let rejected = r.dispatch(&json!({"command":"lease_start"}), 0);
        assert_eq!(rejected["error"], "lease_capacity_reached");
        assert_eq!(rejected["max_active_leases"], MAX_ACTIVE_LEASES);
        assert_eq!(r.leases.len(), MAX_ACTIVE_LEASES);
        r.leases
            .insert(ids[0].clone(), Instant::now() - Duration::from_secs(1));
        let admitted = r.dispatch(&json!({"command":"lease_start"}), 0);
        assert_eq!(admitted["ok"], true);
        assert_eq!(r.leases.len(), MAX_ACTIVE_LEASES);
        assert!(!r.leases.contains_key(&ids[0]));
    }
    #[test]
    fn policy_requires_snapshot() {
        let d = tempfile::tempdir().unwrap();
        assert!(policy(&d.path().join("missing")).is_err());
        fs::write(d.path().join("policy"),r#"{"schema":1,"source":"runtime_hygiene_common","cpu_critical_pct":90,"memory_critical_pct":95,"disk_critical_pct":90,"disk_critical_free_bytes":10737418240}"#).unwrap();
        assert!(policy(&d.path().join("policy")).is_ok());
    }
}
