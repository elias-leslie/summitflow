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

