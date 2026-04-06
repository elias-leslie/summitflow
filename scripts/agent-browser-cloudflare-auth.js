const fs = require('fs');
const path = require('path');
const https = require('https');
const os = require('os');

const CONFIG_FILE = path.join(os.homedir(), '.cloudflare-access');

const CLOUDFLARE_DOMAINS = [
  'agent.summitflow.dev',
  'dev.summitflow.dev',
  'a-term.summitflow.dev',
  'port.summitflow.dev',
  'vantage.summitflow.dev',
  'summitflow.dev',
];

const WEBSOCKET_DOMAINS = [
  'agent.summitflow.dev',
  'dev.summitflow.dev',
  'a-term.summitflow.dev',
  'port.summitflow.dev',
  'vantage.summitflow.dev',
];

let cachedCredentials = null;

function loadCredentials() {
  if (cachedCredentials !== null) {
    return cachedCredentials;
  }

  const envClientId = process.env.CF_ACCESS_CLIENT_ID;
  const envClientSecret = process.env.CF_ACCESS_CLIENT_SECRET;
  if (envClientId && envClientSecret) {
    cachedCredentials = { clientId: envClientId, clientSecret: envClientSecret };
    return cachedCredentials;
  }

  if (!fs.existsSync(CONFIG_FILE)) {
    cachedCredentials = null;
    return null;
  }

  try {
    const config = {};
    for (const line of fs.readFileSync(CONFIG_FILE, 'utf8').split('\n')) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith('#')) {
        continue;
      }
      const [key, ...valueParts] = trimmed.split('=');
      config[key.trim()] = valueParts.join('=').trim();
    }

    if (config.CF_ACCESS_CLIENT_ID && config.CF_ACCESS_CLIENT_SECRET) {
      cachedCredentials = {
        clientId: config.CF_ACCESS_CLIENT_ID,
        clientSecret: config.CF_ACCESS_CLIENT_SECRET,
      };
      return cachedCredentials;
    }
  } catch (error) {
    console.error(`Warning: Failed to read ${CONFIG_FILE}: ${error.message}`);
  }

  cachedCredentials = null;
  return null;
}

function isCloudflareUrl(url) {
  try {
    const { hostname } = new URL(url);
    return CLOUDFLARE_DOMAINS.some((domain) => hostname === domain || hostname.endsWith(`.${domain}`));
  } catch {
    return false;
  }
}

function hasCloudflareCredentials() {
  return loadCredentials() !== null;
}

function getCloudflareHeaders() {
  const creds = loadCredentials();
  if (!creds) {
    return {};
  }
  return {
    'CF-Access-Client-Id': creds.clientId,
    'CF-Access-Client-Secret': creds.clientSecret,
  };
}

function needsWebSocketAuth(url) {
  try {
    const { hostname } = new URL(url);
    return WEBSOCKET_DOMAINS.some((domain) => hostname === domain || hostname.endsWith(`.${domain}`));
  } catch {
    return false;
  }
}

function getApiHost(frontendHost) {
  return frontendHost;
}

async function getCFAuthCookie(host) {
  const creds = loadCredentials();
  if (!creds) {
    return null;
  }

  try {
    return await new Promise((resolve) => {
      const req = https.request({
        hostname: host,
        // Hitting the protected frontend origin is enough to mint the CF cookie.
        // This keeps WebSocket auth same-origin and avoids legacy *api hostnames.
        path: '/',
        method: 'GET',
        headers: {
          'CF-Access-Client-Id': creds.clientId,
          'CF-Access-Client-Secret': creds.clientSecret,
        },
      }, (res) => {
        const cookies = res.headers['set-cookie'] || [];
        for (const cookie of cookies) {
          const match = cookie.match(/CF_Authorization=([^;]+)/);
          if (match) {
            resolve(match[1]);
            return;
          }
        }
        resolve(null);
      });

      req.on('error', () => resolve(null));
      req.setTimeout(10000, () => {
        req.destroy();
        resolve(null);
      });
      req.end();
    });
  } catch (error) {
    console.error(`Warning: Failed to get CF_Authorization cookie for ${host}: ${error.message}`);
    return null;
  }
}

module.exports = {
  getApiHost,
  getCFAuthCookie,
  getCloudflareHeaders,
  hasCloudflareCredentials,
  isCloudflareUrl,
  needsWebSocketAuth,
};
