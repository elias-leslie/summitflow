#!/usr/bin/env node

const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');

const DEFAULT_IDLE_TIMEOUT_MS = 120000;
const DEFAULT_HELPER_TIMEOUT_MS = 7200000;
const DEFAULT_SESSION_NAME = 'default';
const SESSION_NAME_PATTERN = /^[a-zA-Z0-9_-]+$/;

const tryAccess = (p) => { try { fs.accessSync(p, fs.constants.F_OK); return true; } catch { return false; } };
const tryKill0 = (pid) => { try { process.kill(pid, 0); return true; } catch { return false; } };
const removeFile = (p) => { try { fs.unlinkSync(p); } catch { /* ignore */ } };
const sleepMs = (ms) => {
  try { Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms); }
  catch { /* ignore */ }
};

function getIdleTimeoutMs(env = process.env) {
  const raw = env.AGENT_BROWSER_IDLE_TIMEOUT_MS;
  if (!raw) return DEFAULT_IDLE_TIMEOUT_MS;
  const parsed = Number.parseInt(raw, 10);
  return Number.isNaN(parsed) || parsed < 1000 ? DEFAULT_IDLE_TIMEOUT_MS : parsed;
}

function getHelperTimeoutMs(env = process.env) {
  const raw = env.AGENT_BROWSER_HELPER_TIMEOUT_MS;
  if (!raw) return DEFAULT_HELPER_TIMEOUT_MS;
  const parsed = Number.parseInt(raw, 10);
  return Number.isNaN(parsed) || parsed < 60000 ? DEFAULT_HELPER_TIMEOUT_MS : parsed;
}

function getRuntimeLocations(env = process.env) {
  let primary;
  if (env.AGENT_BROWSER_SOCKET_DIR) primary = env.AGENT_BROWSER_SOCKET_DIR;
  else if (env.XDG_RUNTIME_DIR) primary = path.join(env.XDG_RUNTIME_DIR, 'agent-browser');
  else { const h = os.homedir(); primary = h ? path.join(h, '.agent-browser') : path.join(os.tmpdir(), 'agent-browser'); }

  const locations = [{ root: primary, dedicated: true }];
  const homeDir = os.homedir();
  if (homeDir) locations.push({ root: path.join(homeDir, '.agent-browser'), dedicated: true });
  locations.push({ root: os.tmpdir(), dedicated: false });
  return locations.filter((loc, i, arr) => arr.findIndex((e) => e.root === loc.root) === i);
}

function getFileCandidates(sessionName, ext, env = process.env) {
  return getRuntimeLocations(env).flatMap(({ root, dedicated }) => {
    const names = dedicated ? [`${sessionName}.${ext}`, `agent-browser-${sessionName}.${ext}`] : [`agent-browser-${sessionName}.${ext}`];
    return names.map((n) => path.join(root, n));
  });
}

function getHeartbeatCandidates(sessionName, env = process.env) {
  return getRuntimeLocations(env).map(({ root }) => path.join(root, 'heartbeats', `${sessionName}.last-used`));
}

function listSessionLocks(sessionName, env = process.env) {
  const prefix = `${sessionName}.`;
  const lockDirs = [...new Set(getRuntimeLocations(env).map(({ root }) => path.join(root, 'locks')))];
  const matches = [];
  for (const dir of lockDirs) {
    if (!tryAccess(dir)) continue;
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      if (entry.isFile() && entry.name.startsWith(prefix) && entry.name.endsWith('.lock'))
        matches.push(path.join(dir, entry.name));
    }
  }
  return matches;
}

function hasLiveSessionLock(sessionName, env = process.env) {
  let live = false;
  for (const lockPath of listSessionLocks(sessionName, env)) {
    const m = lockPath.match(/\.([0-9]+)\.lock$/);
    const pid = m ? Number.parseInt(m[1], 10) : NaN;
    if (!Number.isNaN(pid) && tryKill0(pid)) { live = true; } else { removeFile(lockPath); }
  }
  return live;
}

function cleanupSessionMetadata(sessionName, env = process.env) {
  for (const p of getHeartbeatCandidates(sessionName, env)) removeFile(p);
  for (const p of listSessionLocks(sessionName, env)) removeFile(p);
}

function cleanupRuntimeFiles(sessionName, env = process.env) {
  for (const ext of ['pid', 'sock', 'port', 'stream'])
    for (const p of getFileCandidates(sessionName, ext, env)) removeFile(p);
  cleanupSessionMetadata(sessionName, env);
}

function readDaemonPid(sessionName, env = process.env) {
  for (const filePath of getFileCandidates(sessionName, 'pid', env)) {
    try {
      const pid = Number.parseInt(fs.readFileSync(filePath, 'utf8').trim(), 10);
      if (!Number.isNaN(pid)) return pid;
    } catch { /* try next */ }
  }
  return null;
}

function getSessionLastActivityMs(sessionName, env = process.env) {
  const candidates = [...getHeartbeatCandidates(sessionName, env), ...getFileCandidates(sessionName, 'pid', env), ...getFileCandidates(sessionName, 'sock', env)];
  let latest = 0;
  for (const p of candidates) { try { latest = Math.max(latest, fs.statSync(p).mtimeMs); } catch { /* skip */ } }
  return latest;
}

function isAgentBrowserDaemon(pid) {
  try { const c = fs.readFileSync(`/proc/${pid}/cmdline`, 'utf8'); return c.includes('agent-browser') && c.includes('daemon.js'); }
  catch { return false; }
}

function readProcessCmdline(pid) {
  try { return fs.readFileSync(`/proc/${pid}/cmdline`, 'utf8'); }
  catch { return ''; }
}

function getProcessParentPid(pid) {
  try {
    const out = execFileSync('ps', ['-o', 'ppid=', '-p', String(pid)], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim();
    const ppid = Number.parseInt(out, 10);
    return Number.isNaN(ppid) ? null : ppid;
  } catch { return null; }
}

function isUserSystemdProcess(pid) {
  if (!pid) return false;
  const cmdline = readProcessCmdline(pid);
  return cmdline.includes('/systemd') && cmdline.includes('--user');
}

function isOrphanedAgentBrowserHelper(pid) {
  const cmdline = readProcessCmdline(pid);
  if (!cmdline.includes('agent-browser-linux-x64')) return false;
  if (cmdline.includes('daemon.js')) return false;
  const ppid = getProcessParentPid(pid);
  return ppid === 1 || isUserSystemdProcess(ppid);
}

function parseSessionNameFromFilename(filename, dedicated) {
  if (filename.endsWith('.pid')) {
    const base = filename.slice(0, -4);
    return base.startsWith('agent-browser-') ? base.slice(14) : dedicated ? base : null;
  }
  if (filename.endsWith('.last-used') || filename.endsWith('.lock')) {
    const base = filename.endsWith('.last-used') ? filename.slice(0, -10) : filename.split('.', 1)[0];
    return dedicated || base.startsWith('agent-browser-') ? base.replace(/^agent-browser-/, '') : null;
  }
  return null;
}

function listSessions(env = process.env) {
  const sessionNames = new Set();
  for (const { root, dedicated } of getRuntimeLocations(env)) {
    if (!tryAccess(root)) continue;
    const addFromDir = (dir) => {
      if (!tryAccess(dir)) return;
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        if (!entry.isFile()) continue;
        const name = parseSessionNameFromFilename(entry.name, dedicated);
        if (name) sessionNames.add(name);
      }
    };
    addFromDir(root);
    for (const sub of ['heartbeats', 'locks']) addFromDir(path.join(root, sub));
  }
  return [...sessionNames].filter((n) => typeof n === 'string' && SESSION_NAME_PATTERN.test(n));
}

function listAgentBrowserDaemonPids() {
  const pids = [];
  for (const entry of fs.readdirSync('/proc', { withFileTypes: true })) {
    if (!entry.isDirectory() || !/^\d+$/.test(entry.name)) continue;
    const pid = Number.parseInt(entry.name, 10);
    if (!Number.isNaN(pid) && isAgentBrowserDaemon(pid)) pids.push(pid);
  }
  return pids;
}

function listOrphanedAgentBrowserHelperPids() {
  const pids = [];
  for (const entry of fs.readdirSync('/proc', { withFileTypes: true })) {
    if (!entry.isDirectory() || !/^\d+$/.test(entry.name)) continue;
    const pid = Number.parseInt(entry.name, 10);
    if (!Number.isNaN(pid) && isOrphanedAgentBrowserHelper(pid)) pids.push(pid);
  }
  return pids;
}

function terminateOrphanedHelper(pid, dryRun) {
  if (dryRun) return;
  process.kill(pid, 'SIGTERM');
  sleepMs(250);
  if (tryKill0(pid)) process.kill(pid, 'SIGKILL');
}

function inferSessionNamesForPid(pid, env = process.env) {
  const names = new Set();
  try {
    const vars = fs.readFileSync(`/proc/${pid}/environ`, 'utf8').split('\0');
    const m = vars.find((e) => e.startsWith('AGENT_BROWSER_SESSION='));
    const s = m ? m.slice('AGENT_BROWSER_SESSION='.length) : null;
    if (typeof s === 'string' && SESSION_NAME_PATTERN.test(s)) names.add(s);
  } catch { /* no environ */ }
  for (const sessionName of listSessions(env)) {
    if (readDaemonPid(sessionName, env) === pid) names.add(sessionName);
  }
  if (names.size === 0) names.add(DEFAULT_SESSION_NAME);
  return [...names];
}

function getProcessAgeMs(pid) {
  try {
    const out = execFileSync('ps', ['-o', 'etimes=', '-p', String(pid)], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim();
    const secs = Number.parseInt(out, 10);
    return Number.isNaN(secs) ? 0 : secs * 1000;
  } catch { return 0; }
}

function getSessionSocketStates(socketLines, socketPaths) {
  const states = [...new Set(socketPaths.filter(Boolean))].map((socketPath) => {
    const lines = socketLines.filter((l) => l.includes(socketPath));
    return { socketPath, hasListenSocket: lines.some((l) => l.includes(' LISTEN ')), hasEstablishedClient: lines.some((l) => l.includes(' ESTAB ') && l.includes(socketPath)) };
  });
  return { states, hasListenSocket: states.some((s) => s.hasListenSocket), hasEstablishedClient: states.some((s) => s.hasEstablishedClient) };
}

function runIdleCleanup(options = {}) {
  const env = options.env || process.env;
  const nowMs = options.nowMs || Date.now();
  const dryRun = options.dryRun === true;
  const verbose = options.verbose === true;
  const timeoutMs = options.timeoutMs || getIdleTimeoutMs(env);
  const helperTimeoutMs = options.helperTimeoutMs || getHelperTimeoutMs(env);
  let socketLines;
  try { socketLines = execFileSync('ss', ['-xapnH'], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).split('\n'); } catch { socketLines = null; }
  const hasSocketInspection = Array.isArray(socketLines);
  const summary = { cleanedStale: [], skippedActive: [], skippedRecent: [], terminatedIdle: [], terminatedHelpers: [] };
  const trackedPids = new Set();

  for (const sessionName of listSessions(env)) {
    const pid = readDaemonPid(sessionName, env);
    const lastActivityMs = getSessionLastActivityMs(sessionName, env);
    const idleForMs = lastActivityMs > 0 ? nowMs - lastActivityMs : timeoutMs + 1;

    if (!pid || !tryKill0(pid) || !isAgentBrowserDaemon(pid)) {
      if (idleForMs < timeoutMs) { summary.skippedRecent.push(sessionName); continue; }
      cleanupRuntimeFiles(sessionName, env); summary.cleanedStale.push(sessionName); continue;
    }
    trackedPids.add(pid);
    if (!hasSocketInspection) { summary.skippedActive.push(sessionName); continue; }

    const sockState = getSessionSocketStates(socketLines, getFileCandidates(sessionName, 'sock', env));
    if (hasLiveSessionLock(sessionName, env) || sockState.hasEstablishedClient) { summary.skippedActive.push(sessionName); continue; }
    if (idleForMs < timeoutMs) { summary.skippedRecent.push(sessionName); continue; }
    if (!sockState.hasListenSocket && sockState.states.some((s) => tryAccess(s.socketPath))) {
      cleanupRuntimeFiles(sessionName, env); summary.cleanedStale.push(sessionName); continue;
    }
    if (!dryRun) { process.kill(pid, 'SIGTERM'); cleanupSessionMetadata(sessionName, env); }
    summary.terminatedIdle.push(sessionName);
  }

  for (const pid of listAgentBrowserDaemonPids()) {
    if (trackedPids.has(pid)) continue;
    const sessionNames = inferSessionNamesForPid(pid, env);
    const hasLiveLock = sessionNames.some((n) => hasLiveSessionLock(n, env));
    const sockState = hasSocketInspection
      ? getSessionSocketStates(socketLines, sessionNames.flatMap((n) => getFileCandidates(n, 'sock', env)))
      : { hasEstablishedClient: false };
    if (hasLiveLock || sockState.hasEstablishedClient) { summary.skippedActive.push(`pid:${pid}`); continue; }
    const ageMs = getProcessAgeMs(pid);
    if (ageMs > 0 && ageMs < timeoutMs) { summary.skippedRecent.push(`pid:${pid}`); continue; }
    if (!dryRun) { process.kill(pid, 'SIGTERM'); for (const n of sessionNames) cleanupRuntimeFiles(n, env); }
    summary.terminatedIdle.push(`pid:${pid}`);
  }

  if (env.AGENT_BROWSER_PRUNE_HELPERS !== '0') {
    for (const pid of listOrphanedAgentBrowserHelperPids()) {
      const ageMs = getProcessAgeMs(pid);
      if (ageMs > 0 && ageMs < helperTimeoutMs) { summary.skippedRecent.push(`helper:${pid}`); continue; }
      terminateOrphanedHelper(pid, dryRun);
      summary.terminatedHelpers.push(`helper:${pid}`);
    }
  }

  if (verbose) {
    const fmt = (label, arr) => `${label}=${arr.join(',') || '-'}`;
    process.stderr.write(`agent-browser cleanup: ${['stale', 'active', 'recent', 'terminated', 'helpers'].map((k, i) => fmt(k, [summary.cleanedStale, summary.skippedActive, summary.skippedRecent, summary.terminatedIdle, summary.terminatedHelpers][i])).join(' ')}\n`);
  }

  return summary;
}

runIdleCleanup({ dryRun: process.argv.includes('--dry-run'), verbose: process.argv.includes('--verbose') });
