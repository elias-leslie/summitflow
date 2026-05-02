# Changelog

## 0.1.2 - 2026-05-02

- Added `st browser endpoint [--http|--ws|--json]` as the canonical CDP target resolver for optional browser tools.
- Expanded agentic browser profiling across Chrome DevTools MCP, Playwright MCP, browser-use, Stagehand, Browser Harness, Verdict, Crawl4AI, Crawlee, Firecrawl, Lightpanda, Kuri, BrowserOS, Steel, Browserless, Skyvern, Selenium, Sentinel, BrowserWing, Unbrowse, Gasoline, and webact.
- Documented final layered ST browser architecture: native VM Chrome core, ST CLI as single source of truth, optional slim DevTools MCP/AI/extraction layers, and rejected default-service/browser-container paths.

## 0.1.1 - 2026-05-02

- Added project-aware `st browser url/open/check <project>` resolution from `project.identity.json`.
- Added native browser VM Chrome runtime scripts and profiling harness.
- Documented agentic browser OSS research, profiling results, and final ST browser architecture.
- Moved normal ST browser runtime away from Docker-based Chrome/Lightpanda on VM 100.
