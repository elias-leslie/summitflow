#!/usr/bin/env node

const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');

const DEFAULT_IDLE_TIMEOUT_MS = 120000;
const DEFAULT_SESSION_NAME = 'default';
const SESSION_NAME_PATTERN = /^[a-zA-Z0-9_-]+$/;

function parseFlags(args) {
  return {
    dryRun: args.includes('--dry-run'),
    verbose: args.includes('--verbose'),
  };
}

function unique(values) {
  return [...new Set(values.filter(Boolean))];
}

function fileExists(filePath) {
  try {
    fs.accessSync(filePath, fs.constants.F_OK);
    return true;
  } catch {
    return false;
  }
}

function removeFile(filePath) {
  try {
    fs.unlinkSync(filePath);
  } catch {
    // Ignore missing and concurrently removed files.
  }
}

function processExists(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

function getIdleTimeoutMs(env = process.env) {
  const rawTimeout = env.AGENT_BROWSER_IDLE_TIMEOUT_MS;
  if (!rawTimeout) {
    return DEFAULT_IDLE_TIMEOUT_MS;
  }

  const parsedTimeout = Number.parseInt(rawTimeout, 10);
  return Number.isNaN(parsedTimeout) || parsedTimeout < 1000
    ? DEFAULT_IDLE_TIMEOUT_MS
    : parsedTimeout;
}

function getPrimaryRuntimeDir(env = process.env) {
  if (env.AGENT_BROWSER_SOCKET_DIR) {
    return env.AGENT_BROWSER_SOCKET_DIR;
  }
  if (env.XDG_RUNTIME_DIR) {
    return path.join(env.XDG_RUNTIME_DIR, 'agent-browser');
  }
  const homeDir = os.homedir();
  if (homeDir) {
    return path.join(homeDir, '.agent-browser');
  }
  return path.join(os.tmpdir(), 'agent-browser');
}

function getRuntimeLocations(env = process.env) {
  const locations = [{ root: getPrimaryRuntimeDir(env), dedicated: true }];
  const homeDir = os.homedir();
  if (homeDir) {
    locations.push({ root: path.join(homeDir, '.agent-browser'), dedicated: true });
  }
  locations.push({ root: os.tmpdir(), dedicated: false });

  return locations.filter((location, index, arr) =>
    arr.findIndex((entry) => entry.root === location.root) === index);
}

function isValidSessionName(sessionName) {
  return typeof sessionName === 'string' && SESSION_NAME_PATTERN.test(sessionName);
}

function getNamedCandidates(sessionName, dedicated, ext) {
  const names = dedicated ? [`${sessionName}.${ext}`] : [];
  names.push(`agent-browser-${sessionName}.${ext}`);
  return names;
}

function getFileCandidates(sessionName, ext, env = process.env) {
  return getRuntimeLocations(env).flatMap(({ root, dedicated }) =>
    getNamedCandidates(sessionName, dedicated, ext).map((name) => path.join(root, name)));
}

function getHeartbeatCandidates(sessionName, env = process.env) {
  return getRuntimeLocations(env).map(({ root }) => path.join(root, 'heartbeats', `${sessionName}.last-used`));
}

function getLockDirs(env = process.env) {
  return unique(getRuntimeLocations(env).map(({ root }) => path.join(root, 'locks')));
}

function listSessionLocks(sessionName, env = process.env) {
  const prefix = `${sessionName}.`;
  const matches = [];

  for (const lockDir of getLockDirs(env)) {
    if (!fileExists(lockDir)) {
      continue;
    }
    for (const entry of fs.readdirSync(lockDir, { withFileTypes: true })) {
      if (entry.isFile() && entry.name.startsWith(prefix) && entry.name.endsWith('.lock')) {
        matches.push(path.join(lockDir, entry.name));
      }
    }
  }

  return matches;
}

function cleanupSessionMetadata(sessionName, env = process.env) {
  for (const filePath of getHeartbeatCandidates(sessionName, env)) {
    removeFile(filePath);
  }
  for (const lockPath of listSessionLocks(sessionName, env)) {
    removeFile(lockPath);
  }
}

function cleanupRuntimeFiles(sessionName, env = process.env) {
  for (const ext of ['pid', 'sock', 'port', 'stream']) {
    for (const filePath of getFileCandidates(sessionName, ext, env)) {
      removeFile(filePath);
    }
  }
  cleanupSessionMetadata(sessionName, env);
}

function readDaemonPid(sessionName, env = process.env) {
  for (const filePath of getFileCandidates(sessionName, 'pid', env)) {
    try {
      const pid = Number.parseInt(fs.readFileSync(filePath, 'utf8').trim(), 10);
      if (!Number.isNaN(pid)) {
        return pid;
      }
    } catch {
      // Try next candidate.
    }
  }
  return null;
}

function getSessionLastActivityMs(sessionName, env = process.env) {
  const candidates = [
    ...getHeartbeatCandidates(sessionName, env),
    ...getFileCandidates(sessionName, 'pid', env),
    ...getFileCandidates(sessionName, 'sock', env),
  ];

  let latestTimestamp = 0;
  for (const filePath of candidates) {
    try {
      latestTimestamp = Math.max(latestTimestamp, fs.statSync(filePath).mtimeMs);
    } catch {
      // Ignore missing artifacts.
    }
  }
  return latestTimestamp;
}

function isAgentBrowserDaemon(pid) {
  try {
    const cmdline = fs.readFileSync(`/proc/${pid}/cmdline`, 'utf8');
    return cmdline.includes('agent-browser') && cmdline.includes('daemon.js');
  } catch {
    return false;
  }
}

function readSocketTable() {
  try {
    return execFileSync('ss', ['-xapnH'], {
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
    }).split('\n');
  } catch {
    return null;
  }
}

function getLockPid(lockPath) {
  const match = lockPath.match(/\.([0-9]+)\.lock$/);
  if (!match) {
    return null;
  }

  const pid = Number.parseInt(match[1], 10);
  return Number.isNaN(pid) ? null : pid;
}

function hasLiveSessionLock(sessionName, env = process.env) {
  let hasLiveLock = false;

  for (const lockPath of listSessionLocks(sessionName, env)) {
    const pid = getLockPid(lockPath);
    if (pid && processExists(pid)) {
      hasLiveLock = true;
      continue;
    }
    removeFile(lockPath);
  }

  return hasLiveLock;
}

function getSessionSocketState(socketLines, socketPath) {
  const matchingLines = socketLines.filter((line) => line.includes(socketPath));
  return {
    socketPath,
    hasListenSocket: matchingLines.some((line) => line.includes(' LISTEN ')),
    hasEstablishedClient: matchingLines.some((line) => line.includes(' ESTAB ') && line.includes(socketPath)),
  };
}

function getSessionSocketStates(socketLines, socketPaths) {
  const states = unique(socketPaths).map((socketPath) => getSessionSocketState(socketLines, socketPath));
  return {
    states,
    hasListenSocket: states.some((state) => state.hasListenSocket),
    hasEstablishedClient: states.some((state) => state.hasEstablishedClient),
  };
}

function parseSessionNameFromFilename(filename, dedicated) {
  if (filename.endsWith('.pid')) {
    const base = filename.slice(0, -'.pid'.length);
    if (base.startsWith('agent-browser-')) {
      return base.slice('agent-browser-'.length);
    }
    return dedicated ? base : null;
  }
  if (filename.endsWith('.last-used')) {
    const base = filename.slice(0, -'.last-used'.length);
    return dedicated || base.startsWith('agent-browser-')
      ? base.replace(/^agent-browser-/, '')
      : null;
  }
  if (filename.endsWith('.lock')) {
    const base = filename.split('.', 1)[0];
    return dedicated || base.startsWith('agent-browser-')
      ? base.replace(/^agent-browser-/, '')
      : null;
  }
  return null;
}

function listSessions(env = process.env) {
  const sessionNames = new Set();

  for (const { root, dedicated } of getRuntimeLocations(env)) {
    if (!fileExists(root)) {
      continue;
    }

    for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
      if (!entry.isFile()) {
        continue;
      }
      const sessionName = parseSessionNameFromFilename(entry.name, dedicated);
      if (sessionName) {
        sessionNames.add(sessionName);
      }
    }

    for (const subdir of ['heartbeats', 'locks']) {
      const fullDir = path.join(root, subdir);
      if (!fileExists(fullDir)) {
        continue;
      }
      for (const entry of fs.readdirSync(fullDir, { withFileTypes: true })) {
        if (!entry.isFile()) {
          continue;
        }
        const sessionName = parseSessionNameFromFilename(entry.name, dedicated);
        if (sessionName) {
          sessionNames.add(sessionName);
        }
      }
    }
  }

  return [...sessionNames].filter((sessionName) => isValidSessionName(sessionName));
}

function listAgentBrowserDaemonPids() {
  const pids = [];

  for (const entry of fs.readdirSync('/proc', { withFileTypes: true })) {
    if (!entry.isDirectory() || !/^\d+$/.test(entry.name)) {
      continue;
    }
    const pid = Number.parseInt(entry.name, 10);
    if (!Number.isNaN(pid) && isAgentBrowserDaemon(pid)) {
      pids.push(pid);
    }
  }

  return pids;
}

function getProcessEnvVar(pid, key) {
  try {
    const variables = fs.readFileSync(`/proc/${pid}/environ`, 'utf8').split('\0');
    const prefix = `${key}=`;
    const match = variables.find((entry) => entry.startsWith(prefix));
    return match ? match.slice(prefix.length) : null;
  } catch {
    return null;
  }
}

function getProcessAgeMs(pid) {
  try {
    const output = execFileSync('ps', ['-o', 'etimes=', '-p', String(pid)], {
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
    }).trim();
    const elapsedSeconds = Number.parseInt(output, 10);
    return Number.isNaN(elapsedSeconds) ? 0 : elapsedSeconds * 1000;
  } catch {
    return 0;
  }
}

function inferSessionNamesForPid(pid, env = process.env) {
  const names = new Set();
  const envSession = getProcessEnvVar(pid, 'AGENT_BROWSER_SESSION');
  if (isValidSessionName(envSession)) {
    names.add(envSession);
  }

  for (const sessionName of listSessions(env)) {
    if (readDaemonPid(sessionName, env) === pid) {
      names.add(sessionName);
    }
  }

  if (names.size === 0) {
    names.add(DEFAULT_SESSION_NAME);
  }

  return [...names];
}

function formatSummary(summary) {
  return [
    `stale=${summary.cleanedStale.join(',') || '-'}`,
    `active=${summary.skippedActive.join(',') || '-'}`,
    `recent=${summary.skippedRecent.join(',') || '-'}`,
    `terminated=${summary.terminatedIdle.join(',') || '-'}`,
  ].join(' ');
}

function runIdleCleanup(options = {}) {
  const env = options.env || process.env;
  const nowMs = options.nowMs || Date.now();
  const dryRun = options.dryRun === true;
  const verbose = options.verbose === true;
  const timeoutMs = options.timeoutMs || getIdleTimeoutMs(env);
  const socketLines = readSocketTable();
  const hasSocketInspection = Array.isArray(socketLines);
  const summary = {
    cleanedStale: [],
    skippedActive: [],
    skippedRecent: [],
    terminatedIdle: [],
  };
  const trackedPids = new Set();

  for (const sessionName of listSessions(env)) {
    const pid = readDaemonPid(sessionName, env);

    if (!pid || !processExists(pid) || !isAgentBrowserDaemon(pid)) {
      cleanupRuntimeFiles(sessionName, env);
      summary.cleanedStale.push(sessionName);
      continue;
    }

    trackedPids.add(pid);

    if (!hasSocketInspection) {
      summary.skippedActive.push(sessionName);
      continue;
    }

    const socketState = getSessionSocketStates(socketLines, getFileCandidates(sessionName, 'sock', env));
    if (hasLiveSessionLock(sessionName, env) || socketState.hasEstablishedClient) {
      summary.skippedActive.push(sessionName);
      continue;
    }

    const lastActivityMs = getSessionLastActivityMs(sessionName, env);
    const idleForMs = lastActivityMs > 0 ? nowMs - lastActivityMs : timeoutMs + 1;
    if (idleForMs < timeoutMs) {
      summary.skippedRecent.push(sessionName);
      continue;
    }

    if (!socketState.hasListenSocket && socketState.states.some((state) => fileExists(state.socketPath))) {
      cleanupRuntimeFiles(sessionName, env);
      summary.cleanedStale.push(sessionName);
      continue;
    }

    if (!dryRun) {
      process.kill(pid, 'SIGTERM');
      cleanupSessionMetadata(sessionName, env);
    }
    summary.terminatedIdle.push(sessionName);
  }

  for (const pid of listAgentBrowserDaemonPids()) {
    if (trackedPids.has(pid)) {
      continue;
    }

    const sessionNames = inferSessionNamesForPid(pid, env);
    const hasLiveLock = sessionNames.some((sessionName) => hasLiveSessionLock(sessionName, env));
    const socketState = hasSocketInspection
      ? getSessionSocketStates(socketLines, sessionNames.flatMap((sessionName) => getFileCandidates(sessionName, 'sock', env)))
      : { hasEstablishedClient: false };

    if (hasLiveLock || socketState.hasEstablishedClient) {
      summary.skippedActive.push(`pid:${pid}`);
      continue;
    }

    const ageMs = getProcessAgeMs(pid);
    if (ageMs > 0 && ageMs < timeoutMs) {
      summary.skippedRecent.push(`pid:${pid}`);
      continue;
    }

    if (!dryRun) {
      process.kill(pid, 'SIGTERM');
      for (const sessionName of sessionNames) {
        cleanupRuntimeFiles(sessionName, env);
      }
    }
    summary.terminatedIdle.push(`pid:${pid}`);
  }

  if (verbose) {
    process.stderr.write(`agent-browser cleanup: ${formatSummary(summary)}\n`);
  }

  return summary;
}

function main() {
  const flags = parseFlags(process.argv.slice(2));
  runIdleCleanup(flags);
}

main();
