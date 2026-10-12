# Changelog

## Unreleased (changes since 0.1.2)

Summary of work from May to October 2026. The package version has not been
bumped.

- Safety: a shared PreToolUse hook for Claude Code and Codex denies direct
  publication and a fixed set of irreversible commands (hard resets, `git
  clean`, recursive deletes of workspace and backup roots, disk, snapshot,
  backup and Proxmox destruction). Deletes of paths another live session owns
  are refused.
- Backups: Restic repositories with local and Google Drive copies, btrbk
  snapshots, an append-only Restic copy on a Proxmox host, backup write
  windows, Proxmox TLS pinning, and a monthly offsite restore test.
- Host monitoring: a Rust collector (`host-monitor/`) that stores host,
  service and process metrics in SQLite, read by `st monitor` and the API.
- Agent operations: fleet session control (`st sessions start`), shared
  admission control for heavy checks and builds, and native acceptance stages
  declared in `.st-check.toml`.
- Extensions: owner projects add `st` commands through versioned extensions
  built on the new `summitflow-st-sdk` package (0.1.1).
- Agent Hub integration goes through the `agent-hub-client` package.
- Operator UI: a file browser for project and workspace files, and a design
  mockup workflow.

## 0.1.2 - 2026-05-02

- Added `st browser endpoint [--http|--ws|--json]` as the canonical CDP target resolver for optional browser tools.
- Expanded agentic browser profiling across Chrome DevTools MCP, Playwright MCP, browser-use, Stagehand, Browser Harness, Verdict, Crawl4AI, Crawlee, Firecrawl, Lightpanda, Kuri, BrowserOS, Steel, Browserless, Skyvern, Selenium, Sentinel, BrowserWing, Unbrowse, Gasoline, and webact.
- Documented final layered ST browser architecture: native VM Chrome core, ST CLI as single source of truth, optional slim DevTools MCP/AI/extraction layers, and rejected default-service/browser-container paths.

## 0.1.1 - 2026-05-02

- Added project-aware `st browser url/open/check <project>` resolution from `project.identity.json`.
- Added native browser VM Chrome runtime scripts and profiling harness.
- Documented agentic browser OSS research, profiling results, and final ST browser architecture.
- Moved normal ST browser runtime away from Docker-based Chrome/Lightpanda on VM 100.
