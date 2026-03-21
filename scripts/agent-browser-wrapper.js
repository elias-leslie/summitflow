#!/usr/bin/env node

const { execFileSync } = require('child_process');
const path = require('path');
const fs = require('fs');
const os = require('os');
const {
  getApiHost,
  getCFAuthCookie,
  getCloudflareHeaders,
  hasCloudflareCredentials,
  isCloudflareUrl,
  needsWebSocketAuth,
} = require('./agent-browser-cloudflare-auth.js');

const SCRIPT_DIR = __dirname;
const MANAGED_ROOT = process.env.AGENT_BROWSER_MANAGED_ROOT || path.join(process.env.HOME, '.local', 'share', 'agent-browser-managed');
const REAL_AGENT_BROWSER = process.env.AGENT_BROWSER_REAL_BIN || path.join(MANAGED_ROOT, 'node_modules', '.bin', 'agent-browser');
const REAPER = process.env.AGENT_BROWSER_REAPER_BIN || path.join(SCRIPT_DIR, 'agent-browser-idle-reaper.js');
const DEFAULT_SESSION_NAME = 'default';

function parseArgs(args) {
  const result = {
    authProvider: null,
    url: null,
    cleanArgs: [],
    isNavigationCommand: false,
  };

  const navigationCommands = ['open', 'goto', 'navigate'];
  let foundCommand = false;

  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];

    if (arg === '--auth' && index + 1 < args.length) {
      result.authProvider = args[index + 1];
      index += 1;
      continue;
    }

    result.cleanArgs.push(arg);
    if (!foundCommand && navigationCommands.includes(arg.toLowerCase())) {
      result.isNavigationCommand = true;
      foundCommand = true;
      continue;
    }
    if (foundCommand && !result.url && !arg.startsWith('-')) {
      result.url = arg;
    }
  }

  return result;
}

function getSocketRoot(env = process.env) {
  if (env.AGENT_BROWSER_SOCKET_DIR) {
    return env.AGENT_BROWSER_SOCKET_DIR;
  }
  if (env.XDG_RUNTIME_DIR) {
    return path.join(env.XDG_RUNTIME_DIR, 'agent-browser');
  }
  if (env.HOME) {
    return path.join(env.HOME, '.agent-browser');
  }
  return path.join(os.tmpdir(), 'agent-browser');
}

function getSessionName(args, env = process.env) {
  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    if (arg === '--session' && index + 1 < args.length) {
      return args[index + 1];
    }
  }
  return env.AGENT_BROWSER_SESSION || DEFAULT_SESSION_NAME;
}

function ensureDir(dirPath) {
  fs.mkdirSync(dirPath, { recursive: true });
}

function buildHeadersArg(existingHeaders, cfHeaders) {
  return JSON.stringify({ ...existingHeaders, ...cfHeaders });
}

function extractExistingHeaders(args) {
  for (let index = 0; index < args.length; index += 1) {
    if (args[index] === '--headers' && index + 1 < args.length) {
      try {
        return JSON.parse(args[index + 1]);
      } catch {
        return {};
      }
    }
  }
  return {};
}

function removeHeadersArg(args) {
  const cleaned = [];
  for (let index = 0; index < args.length; index += 1) {
    if (args[index] === '--headers' && index + 1 < args.length) {
      index += 1;
      continue;
    }
    cleaned.push(args[index]);
  }
  return cleaned;
}

function runAgentBrowser(args) {
  const sessionName = getSessionName(args);
  const hasExplicitSession = args.includes('--session');
  const socketRoot = getSocketRoot();
  const lockDir = path.join(socketRoot, 'locks');
  const lockPath = path.join(lockDir, `${sessionName}.wrapper.lock`);
  const forwardedArgs = hasExplicitSession ? args : ['--session', sessionName, ...args];

  ensureDir(lockDir);

  try {
    // Serialize per-session CLI calls so open/snapshot/eval do not race the same daemon socket.
    execFileSync('flock', ['-w', '30', lockPath, 'node', REAPER], {
      stdio: ['ignore', 'ignore', 'ignore'],
      env: process.env,
    });

    execFileSync('flock', ['-w', '30', lockPath, REAL_AGENT_BROWSER, ...forwardedArgs], {
      stdio: 'inherit',
      env: process.env,
    });
  } catch (error) {
    if (error && typeof error.status === 'number') {
      process.exit(error.status);
    }
    console.error(`Error running agent-browser: ${error.message}`);
    process.exit(2);
  }
}

async function main() {
  const args = process.argv.slice(2);
  const parsed = parseArgs(args);

  if (!parsed.authProvider || parsed.authProvider !== 'cloudflare') {
    runAgentBrowser(args);
    return;
  }

  if (!hasCloudflareCredentials()) {
    console.error('Error: Cloudflare credentials not configured');
    console.error('Create ~/.cloudflare-access with:');
    console.error('  CF_ACCESS_CLIENT_ID=your-client-id');
    console.error('  CF_ACCESS_CLIENT_SECRET=your-client-secret');
    process.exit(2);
  }

  if (parsed.isNavigationCommand && parsed.url && isCloudflareUrl(parsed.url)) {
    const cfHeaders = getCloudflareHeaders();
    const existingHeaders = extractExistingHeaders(parsed.cleanArgs);
    const mergedHeaders = buildHeadersArg(existingHeaders, cfHeaders);
    const argsWithoutHeaders = removeHeadersArg(parsed.cleanArgs);
    const finalArgs = [...argsWithoutHeaders, '--headers', mergedHeaders];

    if (!args.includes('--json')) {
      console.error('Cloudflare Access: Using service token auth');
    }

    if (needsWebSocketAuth(parsed.url)) {
      try {
        const { hostname } = new URL(parsed.url);
        const cfToken = await getCFAuthCookie(getApiHost(hostname));
        if (cfToken && !args.includes('--json')) {
          console.error('Cloudflare Access: WebSocket domain detected, cookies will be set');
        }
      } catch {
        // HTTP headers remain enough for non-WebSocket traffic.
      }
    }

    runAgentBrowser(finalArgs);
    return;
  }

  runAgentBrowser(parsed.cleanArgs);
}

main().catch((error) => {
  console.error(`Error: ${error.message}`);
  process.exit(2);
});
