/**
 * Cloudflare Access Authentication
 *
 * Loads CF Access credentials from environment or config file.
 * Used to authenticate browser automation through Cloudflare Access.
 *
 * Setup:
 *   1. Create service token in Cloudflare dashboard:
 *      Access > Service Auth > Create Service Token
 *   2. Add Service Auth policy to your application
 *   3. Create ~/.cloudflare-access with:
 *      CF_ACCESS_CLIENT_ID=your-client-id
 *      CF_ACCESS_CLIENT_SECRET=your-client-secret
 *
 * Usage:
 *   const { getCloudflareHeaders, isCloudflareUrl } = require('./cloudflare-auth');
 *   const context = await browser.newContext({
 *     extraHTTPHeaders: getCloudflareHeaders()
 *   });
 */

const fs = require("fs");
const path = require("path");

const CONFIG_FILE = path.join(process.env.HOME, ".cloudflare-access");

// Domains that require Cloudflare Access authentication
const CLOUDFLARE_DOMAINS = [
  // Agent Hub environment
  "agent.summitflow.dev",
  "agentapi.summitflow.dev",
  // SummitFlow dev environment
  "dev.summitflow.dev",
  "devapi.summitflow.dev",
  // Terminal environment
  "terminal.summitflow.dev",
  "terminalapi.summitflow.dev",
  // Port subdomain
  "port.summitflow.dev",
  "portapi.summitflow.dev",
  // Base domain
  "summitflow.dev",
];

// Domains that use WebSocket and need cookie-based auth (page.route doesn't intercept WS)
const WEBSOCKET_DOMAINS = [
  "terminal.summitflow.dev",
  "terminalapi.summitflow.dev",
];

let cachedCredentials = null;

/**
 * Load credentials from config file or environment.
 * @returns {{ clientId: string, clientSecret: string } | null}
 */
function loadCredentials() {
  if (cachedCredentials !== null) {
    return cachedCredentials;
  }

  // Try environment variables first
  const envClientId = process.env.CF_ACCESS_CLIENT_ID;
  const envClientSecret = process.env.CF_ACCESS_CLIENT_SECRET;

  if (envClientId && envClientSecret) {
    cachedCredentials = {
      clientId: envClientId,
      clientSecret: envClientSecret,
    };
    return cachedCredentials;
  }

  // Try config file
  if (fs.existsSync(CONFIG_FILE)) {
    try {
      const content = fs.readFileSync(CONFIG_FILE, "utf8");
      const lines = content.split("\n");
      const config = {};

      for (const line of lines) {
        const trimmed = line.trim();
        if (trimmed && !trimmed.startsWith("#")) {
          const [key, ...valueParts] = trimmed.split("=");
          config[key.trim()] = valueParts.join("=").trim();
        }
      }

      if (config.CF_ACCESS_CLIENT_ID && config.CF_ACCESS_CLIENT_SECRET) {
        cachedCredentials = {
          clientId: config.CF_ACCESS_CLIENT_ID,
          clientSecret: config.CF_ACCESS_CLIENT_SECRET,
        };
        return cachedCredentials;
      }
    } catch (e) {
      console.error(`Warning: Failed to read ${CONFIG_FILE}: ${e.message}`);
    }
  }

  cachedCredentials = null;
  return null;
}

/**
 * Check if a URL requires Cloudflare Access authentication.
 * @param {string} url
 * @returns {boolean}
 */
function isCloudflareUrl(url) {
  try {
    const { hostname } = new URL(url);
    return CLOUDFLARE_DOMAINS.some(
      (domain) => hostname === domain || hostname.endsWith("." + domain),
    );
  } catch {
    return false;
  }
}

/**
 * Get Cloudflare Access headers for authenticated requests.
 * Returns empty object if no credentials available.
 * @returns {Record<string, string>}
 */
function getCloudflareHeaders() {
  const creds = loadCredentials();
  if (!creds) {
    return {};
  }

  return {
    "CF-Access-Client-Id": creds.clientId,
    "CF-Access-Client-Secret": creds.clientSecret,
  };
}

/**
 * Get headers for a specific URL - only returns CF headers if URL needs them.
 * @param {string} url
 * @returns {Record<string, string>}
 */
function getHeadersForUrl(url) {
  if (isCloudflareUrl(url)) {
    return getCloudflareHeaders();
  }
  return {};
}

/**
 * Set up request interception to add CF headers only to protected domains.
 * Use this instead of extraHTTPHeaders to avoid CORS issues with third-party resources.
 * @param {Page} page - Playwright page object
 */
async function setupCloudflareAuth(page) {
  const creds = loadCredentials();
  if (!creds) return;

  await page.route("**/*", async (route, request) => {
    const url = request.url();
    if (isCloudflareUrl(url)) {
      // Add CF headers only to protected domains
      const headers = {
        ...request.headers(),
        "CF-Access-Client-Id": creds.clientId,
        "CF-Access-Client-Secret": creds.clientSecret,
      };
      await route.continue({ headers });
    } else {
      // Let other requests pass through unchanged
      await route.continue();
    }
  });
}

/**
 * Check if Cloudflare credentials are configured.
 * @returns {boolean}
 */
function hasCloudflareCredentials() {
  return loadCredentials() !== null;
}

/**
 * Check if a URL's host uses WebSocket and needs cookie-based auth.
 * @param {string} url
 * @returns {boolean}
 */
function needsWebSocketAuth(url) {
  try {
    const { hostname } = new URL(url);
    return WEBSOCKET_DOMAINS.some(
      (domain) => hostname === domain || hostname.endsWith("." + domain),
    );
  } catch {
    return false;
  }
}

/**
 * Get CF_Authorization cookie for a domain using service token auth.
 * Makes an HTTP request with headers and extracts the cookie from response.
 * @param {string} host - The hostname to get cookie for (e.g., 'terminalapi.summitflow.dev')
 * @returns {Promise<string|null>} The CF_Authorization JWT token, or null if failed
 */
async function getCFAuthCookie(host) {
  const creds = loadCredentials();
  if (!creds) return null;

  try {
    // Use https module directly to avoid shell injection
    const https = require("https");
    return new Promise((resolve) => {
      const options = {
        hostname: host,
        path: "/health",
        method: "GET",
        headers: {
          "CF-Access-Client-Id": creds.clientId,
          "CF-Access-Client-Secret": creds.clientSecret,
        },
      };

      const req = https.request(options, (res) => {
        // Extract CF_Authorization from set-cookie header
        const cookies = res.headers["set-cookie"] || [];
        for (const cookie of cookies) {
          const match = cookie.match(/CF_Authorization=([^;]+)/);
          if (match) {
            resolve(match[1]);
            return;
          }
        }
        resolve(null);
      });

      req.on("error", () => resolve(null));
      req.setTimeout(10000, () => {
        req.destroy();
        resolve(null);
      });
      req.end();
    });
  } catch (e) {
    console.error(
      `Warning: Failed to get CF_Authorization cookie for ${host}: ${e.message}`,
    );
    return null;
  }
}

/**
 * Get API host for a frontend host (e.g., terminal.summitflow.dev -> terminalapi.summitflow.dev)
 * @param {string} frontendHost
 * @returns {string}
 */
function getApiHost(frontendHost) {
  // Map frontend hosts to their API hosts
  const apiHostMap = {
    "terminal.summitflow.dev": "terminalapi.summitflow.dev",
    "dev.summitflow.dev": "devapi.summitflow.dev",
    "port.summitflow.dev": "portapi.summitflow.dev",
  };
  return (
    apiHostMap[frontendHost] || frontendHost.replace(/^([^.]+)\./, "$1api.")
  );
}

/**
 * Inject CF_Authorization cookies into browser context for WebSocket auth.
 * Call this BEFORE navigation to ensure WebSocket connections are authenticated.
 * @param {BrowserContext} context - Playwright browser context
 * @param {string} url - The URL being navigated to
 * @returns {Promise<boolean>} True if cookies were injected, false otherwise
 */
async function injectCloudflareAuthCookies(context, url) {
  if (!needsWebSocketAuth(url)) {
    return false;
  }

  try {
    const { hostname: frontendHost } = new URL(url);
    const apiHost = getApiHost(frontendHost);

    // Get the CF_Authorization cookie via authenticated HTTP request
    const cfToken = await getCFAuthCookie(apiHost);
    if (!cfToken) {
      console.error(`Warning: Could not get CF auth cookie for ${apiHost}`);
      return false;
    }

    // Inject cookies for both frontend and API domains
    const cookies = [
      {
        name: "CF_Authorization",
        value: cfToken,
        domain: frontendHost,
        path: "/",
        secure: true,
        sameSite: "None",
      },
      {
        name: "CF_Authorization",
        value: cfToken,
        domain: apiHost,
        path: "/",
        secure: true,
        sameSite: "None",
      },
    ];

    await context.addCookies(cookies);
    console.log("Cloudflare Access: Cookies injected for WebSocket auth");
    return true;
  } catch (e) {
    console.error(`Warning: Failed to inject CF auth cookies: ${e.message}`);
    return false;
  }
}

module.exports = {
  getCloudflareHeaders,
  getHeadersForUrl,
  isCloudflareUrl,
  hasCloudflareCredentials,
  setupCloudflareAuth,
  needsWebSocketAuth,
  getCFAuthCookie,
  getApiHost,
  injectCloudflareAuthCookies,
  CLOUDFLARE_DOMAINS,
  WEBSOCKET_DOMAINS,
  CONFIG_FILE,
};
