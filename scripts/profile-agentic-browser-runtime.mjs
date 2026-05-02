#!/usr/bin/env node
import { execFileSync } from "node:child_process";
import http from "node:http";
import https from "node:https";

const DEFAULT_TARGETS = [
  { name: "terminal", url: "https://terminal.summitflow.dev/" },
  { name: "summitflow", url: "https://dev.summitflow.dev/" },
  { name: "agent-hub", url: "https://agent.summitflow.dev/" },
  { name: "portfolio", url: "https://port.summitflow.dev/" },
  {
    name: "synthetic-action",
    action: true,
    url:
      "data:text/html;charset=utf-8," +
      encodeURIComponent(`<!doctype html>
<html>
<head><title>Agent action target</title></head>
<body>
  <main>
    <h1>Agent action target</h1>
    <label>Name <input id="name" aria-label="Name"></label>
    <button id="go">Submit</button>
    <p id="result">Waiting</p>
  </main>
  <script>
    document.getElementById('go').addEventListener('click', () => {
      document.getElementById('result').textContent = 'Submitted ' + document.getElementById('name').value;
    });
  </script>
</body>
</html>`),
  },
];

const DEFAULT_ENGINES = {
  "chrome-container": "http://127.0.0.1:9222",
  lightpanda: "http://127.0.0.1:9223",
};

function jsonLine(value) {
  process.stdout.write(`${JSON.stringify(value)}\n`);
}

function parseJsonEnv(name, fallback) {
  const raw = process.env[name];
  if (!raw) return fallback;
  try {
    return JSON.parse(raw);
  } catch (error) {
    jsonLine({ event: "config_error", name, error: error.message });
    return fallback;
  }
}

function parseEngines() {
  const raw = process.env.ST_BROWSER_PROFILE_ENGINES;
  if (!raw) return DEFAULT_ENGINES;
  return Object.fromEntries(
    raw
      .split(",")
      .map((part) => part.trim())
      .filter(Boolean)
      .map((part) => {
        const [name, endpoint] = part.split("=", 2);
        return [name.trim(), endpoint.trim()];
      })
      .filter(([name, endpoint]) => name && endpoint),
  );
}

function getJson(url) {
  return new Promise((resolve, reject) => {
    const client = url.startsWith("https:") ? https : http;
    const request = client.get(url, { timeout: 5000 }, (response) => {
      let body = "";
      response.setEncoding("utf8");
      response.on("data", (chunk) => {
        body += chunk;
      });
      response.on("end", () => {
        try {
          resolve(JSON.parse(body));
        } catch (error) {
          reject(error);
        }
      });
    });
    request.on("timeout", () => {
      request.destroy(new Error(`timeout ${url}`));
    });
    request.on("error", reject);
  });
}

function normalizeWsEndpoint(wsEndpoint, endpoint) {
  const endpointUrl = new URL(endpoint);
  return wsEndpoint
    .replace("0.0.0.0:9222", endpointUrl.host)
    .replace("127.0.0.1:9222", endpointUrl.host)
    .replace("127.0.0.1:9323", endpointUrl.host)
    .replace("localhost:9222", endpointUrl.host);
}

function dockerStats() {
  try {
    const output = execFileSync("docker", ["stats", "--no-stream", "--format", "{{json .}}"], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    });
    return output
      .trim()
      .split("\n")
      .filter(Boolean)
      .map((line) => JSON.parse(line));
  } catch {
    return [];
  }
}

function descendants(pid) {
  const out = execFileSync("ps", ["-eo", "pid=,ppid=,rss=,pcpu=,comm="], { encoding: "utf8" });
  const rows = out
    .trim()
    .split("\n")
    .map((line) => line.trim().split(/\s+/, 5))
    .map(([rowPid, rowPpid, rss, cpu, command]) => ({
      pid: Number(rowPid),
      ppid: Number(rowPpid),
      rssKb: Number(rss),
      cpu: Number(cpu),
      command,
    }))
    .filter((row) => Number.isFinite(row.pid));
  const queue = [pid];
  const seen = new Set(queue);
  for (let index = 0; index < queue.length; index += 1) {
    for (const row of rows) {
      if (row.ppid === queue[index] && !seen.has(row.pid)) {
        seen.add(row.pid);
        queue.push(row.pid);
      }
    }
  }
  const selected = rows.filter((row) => seen.has(row.pid));
  return {
    rssKb: selected.reduce((sum, row) => sum + (row.rssKb || 0), 0),
    cpu: Number(selected.reduce((sum, row) => sum + (row.cpu || 0), 0).toFixed(2)),
    processes: selected.length,
  };
}

function nativeStats() {
  const rawPid = process.env.ST_BROWSER_PROFILE_NATIVE_PID;
  if (!rawPid) return null;
  const pid = Number(rawPid);
  if (!Number.isFinite(pid)) return null;
  try {
    return descendants(pid);
  } catch {
    return null;
  }
}

function resourceSnapshot() {
  return { docker: dockerStats(), native: nativeStats() };
}

function estimateTokens(value) {
  return Math.ceil(String(value || "").length / 4);
}

async function run() {
  const { default: puppeteer } = await import("puppeteer-core");
  const iterations = Number(process.env.ST_BROWSER_PROFILE_ITERATIONS || "2");
  const targets = parseJsonEnv("ST_BROWSER_PROFILE_TARGETS", DEFAULT_TARGETS);
  const engines = parseEngines();

  jsonLine({ event: "start", iterations, targets: targets.map((target) => target.name), engines: Object.keys(engines) });
  jsonLine({ event: "resources_before", resources: resourceSnapshot() });

  const summaries = new Map();
  for (const [engine, endpoint] of Object.entries(engines)) {
    const summary = { ok: 0, fail: 0, totalMs: 0, snapshotTokens: 0, screenshotBytes: 0 };
    summaries.set(engine, summary);
    let browser;
    try {
      const version = await getJson(`${endpoint.replace(/\/$/, "")}/json/version`);
      const wsEndpoint = normalizeWsEndpoint(version.webSocketDebuggerUrl, endpoint);
      const connectStart = performance.now();
      browser = await puppeteer.connect({ browserWSEndpoint: wsEndpoint });
      const connectMs = Math.round(performance.now() - connectStart);
      jsonLine({ event: "connect", engine, endpoint, connectMs, browser: version.Browser || "unknown" });
    } catch (error) {
      jsonLine({ event: "connect_error", engine, endpoint, error: error.message });
      summary.fail += targets.length * iterations;
      continue;
    }

    for (const target of targets) {
      for (let iteration = 1; iteration <= iterations; iteration += 1) {
        const runStart = performance.now();
        const result = { event: "result", engine, target: target.name, iteration, status: "ok" };
        let page;
        try {
          const pageStart = performance.now();
          page = await browser.newPage();
          result.newPageMs = Math.round(performance.now() - pageStart);
          await page.setViewport({ width: 1280, height: 800, deviceScaleFactor: 1 });
          const navStart = performance.now();
          await page.goto(target.url, { waitUntil: "domcontentloaded", timeout: 20000 });
          result.navMs = Math.round(performance.now() - navStart);
          await new Promise((resolve) => setTimeout(resolve, 500));
          if (target.action) {
            const actionStart = performance.now();
            await page.type("#name", "SummitFlow");
            await page.click("#go");
            result.actionText = await page.$eval("#result", (node) => node.textContent);
            result.actionMs = Math.round(performance.now() - actionStart);
          }
          const compactStart = performance.now();
          const snapshot = await page.evaluate(() => {
            const visibleText = (document.body?.innerText || "").replace(/\s+/g, " ").trim().slice(0, 4000);
            const interactive = Array.from(document.querySelectorAll("a,button,input,textarea,select,[role='button'],[tabindex]"))
              .slice(0, 80)
              .map((node) => {
                const rect = node.getBoundingClientRect();
                return {
                  tag: node.tagName.toLowerCase(),
                  type: node.getAttribute("type") || "",
                  role: node.getAttribute("role") || "",
                  name:
                    node.getAttribute("aria-label") ||
                    node.getAttribute("placeholder") ||
                    node.textContent?.trim().slice(0, 80) ||
                    node.getAttribute("name") ||
                    "",
                  x: Math.round(rect.x),
                  y: Math.round(rect.y),
                  w: Math.round(rect.width),
                  h: Math.round(rect.height),
                };
              });
            return {
              url: location.href,
              title: document.title,
              text: visibleText,
              interactive,
              fullTextChars: document.body?.innerText?.length || 0,
              htmlChars: document.body?.innerHTML?.length || 0,
              nodes: document.querySelectorAll("*").length,
            };
          });
          const compact = JSON.stringify(snapshot);
          result.snapshotMs = Math.round(performance.now() - compactStart);
          result.snapshotChars = compact.length;
          result.snapshotTokens = estimateTokens(compact);
          result.fullTextChars = snapshot.fullTextChars;
          result.htmlChars = snapshot.htmlChars;
          result.nodes = snapshot.nodes;
          result.interactiveCount = snapshot.interactive.length;
          try {
            const image = await page.screenshot({ type: "png" });
            result.screenshotBytes = image.length;
          } catch (error) {
            result.screenshotError = error.message.slice(0, 160);
          }
          result.totalMs = Math.round(performance.now() - runStart);
          summary.ok += 1;
          summary.totalMs += result.totalMs;
          summary.snapshotTokens += result.snapshotTokens;
          summary.screenshotBytes += result.screenshotBytes || 0;
        } catch (error) {
          result.status = "error";
          result.error = error.message.slice(0, 240);
          result.totalMs = Math.round(performance.now() - runStart);
          summary.fail += 1;
        } finally {
          try {
            await page?.close();
          } catch {}
        }
        jsonLine(result);
      }
    }
    try {
      browser.disconnect();
    } catch {}
  }

  jsonLine({ event: "resources_after", resources: resourceSnapshot() });
  for (const [engine, summary] of summaries.entries()) {
    jsonLine({
      event: "summary",
      engine,
      ok: summary.ok,
      fail: summary.fail,
      avgMs: summary.ok ? Math.round(summary.totalMs / summary.ok) : null,
      avgSnapshotTokens: summary.ok ? Math.round(summary.snapshotTokens / summary.ok) : null,
      avgScreenshotBytes: summary.ok ? Math.round(summary.screenshotBytes / summary.ok) : null,
    });
  }
}

run().catch((error) => {
  jsonLine({ event: "fatal", error: error.message, stack: error.stack });
  process.exitCode = 1;
});
