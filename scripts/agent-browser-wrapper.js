#!/usr/bin/env node

const { execFileSync, spawn } = require('child_process');
const path = require('path');
const {
  getApiHost,
  getCFAuthCookie,
  getCloudflareHeaders,
  hasCloudflareCredentials,
  isCloudflareUrl,
  needsWebSocketAuth,
} = require('./agent-browser-cloudflare-auth.js');

const MANAGED_ROOT = process.env.AGENT_BROWSER_MANAGED_ROOT || path.join(process.env.HOME, '.local', 'share', 'agent-browser-managed');
const REAL_AGENT_BROWSER = process.env.AGENT_BROWSER_REAL_BIN || path.join(MANAGED_ROOT, 'node_modules', '.bin', 'agent-browser');
const REAPER = process.env.AGENT_BROWSER_REAPER_BIN || path.join(process.env.HOME, 'summitflow', 'scripts', 'agent-browser-idle-reaper.js');

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

function runReaper() {
  try {
    execFileSync(REAPER, [], {
      stdio: ['ignore', 'ignore', 'ignore'],
      env: process.env,
    });
  } catch {
    // Never block browser use on cleanup failures.
  }
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
  runReaper();

  const child = spawn(REAL_AGENT_BROWSER, args, {
    stdio: 'inherit',
    env: process.env,
  });

  child.on('close', (code) => {
    process.exit(code || 0);
  });

  child.on('error', (error) => {
    console.error(`Error running agent-browser: ${error.message}`);
    process.exit(2);
  });
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
