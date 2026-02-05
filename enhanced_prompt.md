Add a system health status widget to the main dashboard showing CPU/Mem usage.

**DESIGN SYSTEM (REQUIRED):**
- **Platform**: Web, Desktop-first dashboard.
- **Theme**: Outrun / Cyberpunk Intelligence (Dark Mode).
- **Background**: Deep Void (`#0a0612`) for page, Surface Base (`#150d20`) for widget card.
- **Primary Accent**: Neon Pink (`#ff0066`) for critical stats/actions.
- **Secondary Accent**: Neon Cyan (`#00f5ff`) for healthy stats/info.
- **Typography**: `Space Grotesk` headings, `JetBrains Mono` for data values.
- **Shapes**: Rounded-lg cards, Rounded-md buttons.
- **Effects**: Subtle glow (`shadow-outrun`) on active elements.

**Page Structure / Component Details:**
1.  **Widget Container**:
    -   Style: `card-elevated` (Gradient slate-850, border slate-700).
    -   Header: "System Status" in `text-sm font-medium text-slate-400`.
    -   Action: "Refresh" ghost button (icon only) in top-right.

2.  **Metrics Grid**:
    -   Layout: 2 columns (CPU, Memory).
    -   **CPU Metric**:
        -   Label: "CPU Load" (`text-xs text-slate-500`).
        -   Value: "42%" (`text-2xl font-mono text-neon-cyan`).
        -   Visual: Mini progress bar (`bg-slate-800` track, `bg-neon-cyan` fill).
    -   **Memory Metric**:
        -   Label: "Memory" (`text-xs text-slate-500`).
        -   Value: "6.4 GB" (`text-2xl font-mono text-outrun-300`).
        -   Visual: Mini progress bar (`bg-slate-800` track, `bg-outrun-400` fill).

3.  **Status Indicator**:
    -   Footer area.
    -   Badge: "All Systems Operational" (`badge-outrun` or `badge-cyan`).
    -   Dot: Pulsing neon cyan dot (`status-dot healthy animate-pulse`).

**Context**:
This is a new component `SystemHealthWidget.tsx` to be placed on the main dashboard. It should use `lucide-react` icons (Activity, RefreshCw).
