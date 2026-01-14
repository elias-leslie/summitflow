/**
 * Browser Client - Connect to pre-warmed browser server
 *
 * Provides getBrowser() that connects to running server or falls back to launch.
 *
 * Usage:
 *   const { getBrowser, closeBrowser } = require('./browser-client');
 *   const browser = await getBrowser();
 *   // ... use browser
 *   await closeBrowser(browser);  // Only closes if we launched it
 */

const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const WS_FILE = path.join(process.env.HOME, '.browser-server-ws');

// Track whether we launched the browser ourselves
let launchedLocally = false;

/**
 * Get a browser instance - connects to server if available, otherwise launches.
 * @returns {Promise<Browser>}
 */
async function getBrowser() {
  // Try to connect to pre-warmed server
  if (fs.existsSync(WS_FILE)) {
    const wsEndpoint = fs.readFileSync(WS_FILE, 'utf8').trim();
    try {
      const browser = await chromium.connect(wsEndpoint, { timeout: 1000 });
      launchedLocally = false;
      return browser;
    } catch (e) {
      // Server not responding, fall through to launch
    }
  }

  // Fallback: launch new browser
  launchedLocally = true;
  return chromium.launch({ headless: true });
}

/**
 * Close browser - closes local browser, disconnects from server.
 * When connected to server, close() just disconnects (doesn't stop browser).
 * @param {Browser} browser
 */
async function closeBrowser(browser) {
  // Always call close() - for local it closes browser, for server it disconnects
  await browser.close();
}

/**
 * Check if we're connected to the server or using a local browser.
 * @returns {boolean}
 */
function isServerConnected() {
  return !launchedLocally;
}

module.exports = { getBrowser, closeBrowser, isServerConnected };
