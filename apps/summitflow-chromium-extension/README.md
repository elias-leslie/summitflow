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

