# SummitFlow Windows Connector

Dedicated-profile launcher and local bridge for Davion-Sidar Windows
Co-Browser sessions.

Scope:

- launch only the SummitFlow-dedicated Chromium profile
- pair to SummitFlow with a short-lived token
- expose connector status, profile identity, and reviewable egress
- revoke locally and on SummitFlow teardown
- bridge WebRTC pixels and WebSocket/DataChannel metadata
- refuse normal profile paths and long-lived grants

Non-goals:

- no access to regular Chrome/Edge user-data directories
- no broad remote desktop control
- no persistent screenshots, DOM replay, credential text, MFA, passkeys, cookies,
  or clipboard payloads
- no hidden network egress

Planned package shape:

- lightweight launcher/companion service
- local loopback bridge bound to one session token
- profile directory allowlist
- egress preview and revoke UI
- install/update notes for Davion-Sidar

Current implementation:

- claims a short-lived SummitFlow connector pairing token
- launches Chrome/Chromium/Edge with a dedicated `--user-data-dir`
- loads only the SummitFlow Chromium extension from `apps/summitflow-chromium-extension`
- exposes reviewable egress before launch
- serves a one-time loopback `/extension-session` bridge for the extension background worker
- keeps the connector token in process memory; stdout never prints it
- exposes local `/revoke`, `/health`, and `/egress` endpoints on `127.0.0.1`

Build:

```bash
pnpm --filter @summitflow/windows-connector build
```

Dry run:

```bash
pnpm --filter @summitflow/windows-connector build
node apps/summitflow-windows-connector/dist/cli.js --dry-run --yes
```

Launch shape:

```bash
summitflow-windows-connector \
  --api http://127.0.0.1:8001/api \
  --pairing-id pairing-... \
  --pairing-token ... \
  --yes
```
