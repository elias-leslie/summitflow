# SummitFlow Chromium Extension

Dedicated-profile extension for Windows Co-Browser Design Review sessions.

Scope:

- render the in-page collaboration overlay
- sync URL, viewport, scroll, selector anchors, and bounding boxes
- publish pointer, box, highlight, arrow, and comment events
- bridge compact page state to SummitFlow through the connector
- enforce sensitive-mode suppression in content scripts

Non-goals:

- no normal Chrome/Edge profile access
- no password manager, passkey, cookie, history, tab, or clipboard-history access
- no full DOM dumps or replay stream in agent context
- no raw connector token or CDP URL in page state

Planned package shape:

- `manifest.json`
- `src/background.ts`
- `src/content.ts`
- `src/overlay.ts`
- `src/pairing.ts`
- minimal host permissions granted from active Design Review session target

Current implementation:

- Manifest V3 extension with no persistent host permissions.
- `activeTab` plus `scripting` injects the content overlay into the visible tab.
- Localhost host permission is limited to the Windows connector bridge.
- Background worker stores the connector token in `chrome.storage.session`.
- Content script never receives the raw connector token.
- Heartbeats send URL, title, viewport, scroll, and optional non-sensitive DOM hash only.
- Overlay supports pin, box, highlight, and comment capture through compact anchors/selectors.

Build:

```bash
pnpm --filter @summitflow/chromium-extension build
```
