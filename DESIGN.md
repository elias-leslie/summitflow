# Design System: SummitFlow
**Project ID**: summitflow

## 1. Visual Theme & Atmosphere
**"Outrun / Cyberpunk Intelligence"**
The interface features a deep, immersive dark mode inspired by 80s retro-futurism (Outrun) blended with modern developer tooling aesthetics. It feels "dense," "technical," and "alive."
-   **Vibe**: High-contrast, neon-accented, terminal-inspired.
-   **Lighting**: Glowing elements against deep voids. Use of scanlines and grid patterns to evoke a CRT or digital workspace feel.
-   **Density**: High information density, suitable for complex management tasks.

## 2. Color Palette & Roles

### Backgrounds & Surfaces
-   **Deep Void** (`#0a0612` / `slate-950`): Main application background.
-   **Surface Base** (`#150d20` / `slate-850`): Cards, panels, and elevated areas.
-   **Surface Highlight** (`#2d1d42` / `slate-700`): Borders, dividers, and hover states.

### Primary Accents (The "Outrun" Scale)
-   **Neon Pink** (`#ff0066` / `outrun-500`): **Primary Action Color**. Used for main buttons, critical indicators, and active states.
-   **Deep Magenta** (`#800033` / `outrun-900`): Backgrounds for active elements, deep gradients.
-   **Soft Pink** (`#ffc2db` / `outrun-200`): Highlights on pink elements.

### Secondary Accents (Neon & Functional)
-   **Cyber Cyan** (`#00f5ff` / `neon-cyan`): **Info & Focus**. Used for focus rings, selection states, and information indicators.
-   **Sunset Orange** (`#ff6600` / `sunset-orange`): **High Priority**.
-   **Sunset Yellow** (`#fff200` / `sunset-yellow`): **Warning/Attention**.

### Semantic Colors
-   **Critical/Error**: `#f43f5e` (Rose-500) or `#ff0066` (Outrun-500)
-   **Warning**: `#f59e0b` (Amber-500)
-   **Success**: `#00f5ff` (Neon Cyan) - *Note: Cyan is used for success in this theme, diverging from standard green.*

## 3. Typography Rules

### Font Families
-   **Display/Headings**: `Space Grotesk` (Sans-serif, geometric, tech-feel). Use for page titles and major headers.
-   **Body/UI**: `IBM Plex Sans` (Sans-serif, humanist, legible). Default for all standard text.
-   **Code/Mono**: `JetBrains Mono` or `Fira Code`. Used for snippets, logs, IDs, and tabular data.

### Sizing & Weight
-   **Headings**: Bold (700) or SemiBold (600).
-   **Body**: Regular (400) or Medium (500) for emphasis.
-   **Sizes**: Standard Tailwind scale, but leaning small (`text-sm`, `text-xs`) for UI density.

## 4. Component Stylings

### Buttons
-   **Primary**: `bg-outrun-600` hover `bg-outrun-500`. Text white. Glow effect (`shadow-outrun`). Rounded-md.
-   **Secondary**: `bg-slate-750` border `slate-600`. Text `slate-200`. Hover border `outrun-500/30`.
-   **Ghost**: Transparent. Text `slate-400`. Hover `text-outrun-400` bg `slate-800/50`.

### Cards ([shadcn/ui] primitives)
-   **Base**: `bg-slate-850` border `slate-700`. Rounded-lg (`radius-lg`).
-   **Elevated**: Gradient background (135deg slate-850 to slate-900). Subtle pink border highlight (`rgba(255, 0, 102, 0.05)`).
-   **Effects**: Often use `backdrop-blur` if overlaying content.

### Inputs & Forms
-   **Style**: `bg-slate-900` border `slate-700`. Rounded-md.
-   **Focus**: `ring-1` `ring-outrun-500/30` border `outrun-500/50`. No default browser outline.

### Badges
-   **Outrun**: `bg-outrun-500/10` text `outrun-400` border `outrun-500/30`.
-   **Shape**: `rounded` (not full pill), `px-2 py-0.5`.

## 5. Layout Principles
-   **Grid Background**: Pages often feature a subtle background grid (`bg-grid-pattern`) to emphasize the "workspace" feel.
-   **Spacing**: Dense. Use `gap-2` or `gap-4` for tight grouping.
-   **Scanlines**: Subtle CRT scanline overlay on the body.
-   **Borders**: Thin, precise borders (`1px`). Neon glow borders (`border-glow`) for active active panels.
