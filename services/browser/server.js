#!/usr/bin/env node
/**
 * Persistent Browser Server Daemon
 *
 * Keeps a Chromium browser running for instant screenshots and automation.
 * Scripts connect via browserType.connect() instead of launching new browsers.
 *
 * Usage:
 *   node server.js              # Start server (foreground)
 *   node server.js --status     # Check if server is running
 *   node server.js --stop       # Stop the server
 *
 * WebSocket endpoint is written to: ~/.browser-server-ws
 *
 * Expected performance: <200ms screenshots (vs ~1.5s with fresh launch)
 */

const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const http = require('http');

const WS_FILE = path.join(process.env.HOME, '.browser-server-ws');
const PID_FILE = path.join(process.env.HOME, '.browser-server-pid');
const PORT = 9323; // Health check port

async function startServer() {
  console.log('Starting browser server daemon...');

  // Check if already running
  if (fs.existsSync(WS_FILE)) {
    const wsEndpoint = fs.readFileSync(WS_FILE, 'utf8').trim();
    try {
      const browser = await chromium.connect(wsEndpoint, { timeout: 2000 });
      console.log('Server already running at:', wsEndpoint);
      await browser.close();
      process.exit(0);
    } catch (e) {
      // Server not actually running, clean up stale files
      fs.unlinkSync(WS_FILE);
      if (fs.existsSync(PID_FILE)) fs.unlinkSync(PID_FILE);
    }
  }

  // Launch browser server
  const browserServer = await chromium.launchServer({
    headless: true,
    args: [
      '--disable-dev-shm-usage',
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-gpu',
    ],
  });

  const wsEndpoint = browserServer.wsEndpoint();
  console.log('Browser server started');
  console.log('WebSocket endpoint:', wsEndpoint);

  // Write endpoint to file for clients
  fs.writeFileSync(WS_FILE, wsEndpoint);
  fs.writeFileSync(PID_FILE, process.pid.toString());

  // Health check HTTP server
  const healthServer = http.createServer((req, res) => {
    if (req.url === '/health') {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({
        status: 'ok',
        wsEndpoint,
        pid: process.pid,
        uptime: process.uptime(),
      }));
    } else if (req.url === '/ws') {
      res.writeHead(200, { 'Content-Type': 'text/plain' });
      res.end(wsEndpoint);
    } else {
      res.writeHead(404);
      res.end('Not found');
    }
  });

  healthServer.listen(PORT, '127.0.0.1', () => {
    console.log(`Health check: http://127.0.0.1:${PORT}/health`);
    console.log(`WebSocket URL: http://127.0.0.1:${PORT}/ws`);
  });

  // Cleanup on exit
  const cleanup = async () => {
    console.log('\nShutting down browser server...');
    try {
      healthServer.close();
      await browserServer.close();
    } catch (e) {
      // Ignore errors during cleanup
    }
    if (fs.existsSync(WS_FILE)) fs.unlinkSync(WS_FILE);
    if (fs.existsSync(PID_FILE)) fs.unlinkSync(PID_FILE);
    console.log('Browser server stopped');
    process.exit(0);
  };

  process.on('SIGINT', cleanup);
  process.on('SIGTERM', cleanup);
  process.on('SIGHUP', cleanup);

  // Keep process running
  console.log('\nBrowser server running. Press Ctrl+C to stop.');
}

async function checkStatus() {
  if (!fs.existsSync(WS_FILE)) {
    console.log('Browser server is not running');
    process.exit(1);
  }

  const wsEndpoint = fs.readFileSync(WS_FILE, 'utf8').trim();
  try {
    const browser = await chromium.connect(wsEndpoint, { timeout: 2000 });
    const contexts = browser.contexts().length;
    console.log('Browser server is running');
    console.log('WebSocket:', wsEndpoint);
    console.log('Active contexts:', contexts);
    await browser.close();
    process.exit(0);
  } catch (e) {
    console.log('Browser server appears dead (stale endpoint file)');
    fs.unlinkSync(WS_FILE);
    if (fs.existsSync(PID_FILE)) fs.unlinkSync(PID_FILE);
    process.exit(1);
  }
}

async function stopServer() {
  if (!fs.existsSync(PID_FILE)) {
    console.log('No PID file found - server may not be running');
    if (fs.existsSync(WS_FILE)) fs.unlinkSync(WS_FILE);
    process.exit(0);
  }

  const pid = parseInt(fs.readFileSync(PID_FILE, 'utf8').trim());
  try {
    process.kill(pid, 'SIGTERM');
    console.log(`Sent SIGTERM to PID ${pid}`);
    // Wait a bit for cleanup
    await new Promise(r => setTimeout(r, 1000));
  } catch (e) {
    console.log(`Process ${pid} not found - cleaning up files`);
  }

  if (fs.existsSync(WS_FILE)) fs.unlinkSync(WS_FILE);
  if (fs.existsSync(PID_FILE)) fs.unlinkSync(PID_FILE);
  console.log('Browser server stopped');
  process.exit(0);
}

// Main
const args = process.argv.slice(2);

if (args.includes('--status')) {
  checkStatus();
} else if (args.includes('--stop')) {
  stopServer();
} else {
  startServer();
}
