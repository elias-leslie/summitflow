# Task: Refine TopBar Logo Animation

We are trying to implement a specific "Cinematic Reveal" animation for the logo in the `TopBar.tsx` component (Next.js/Tailwind).

## Assets
-   `public/logo.svg`: Standard square logo (56x56).
-   `public/logo-wide.svg`: Panoramic version (360x100). The center 56px is identical to `logo.svg`.

## Requirements
Implement a 3-stage animation triggered on click:
1.  **Text Collapse**: The "SummitFlow" text next to the logo should collapse/disappear (width -> 0). **Do NOT use opacity fades.**
2.  **Shift to Center**: The square logo icon should move from its left-aligned position to the center of the *target* wide area.
3.  **Expand**: The view should expand (reveal) outwards from that center point to show the full `logo-wide.svg`.

## Critical Constraints
1.  **Zero Layout Shift**: The animation must NOT cause sibling elements (like the vertical divider or Project Selector) to move. The logo container's footprint in the flex document flow must remain static (e.g., fixed width of ~220px). The expansion must happen "visually" (e.g., `position: absolute`, `z-index`, or distinct overlay) without affecting the flexbox layout.
2.  **Seamless Transition**: The transition between the "square" state and "wide" state must be imperceptible. Use `logo-wide.svg` masked as the square version if necessary to ensure pixel-perfect alignment.
3.  **NO FADING**: **Absolutely no opacity fades or cross-fades.** The transition must be achieved through masking, width changes, or movement only. The user strictly forbids fading effects.

## Current State
`TopBar.tsx` currently attempts this but needs refinement on the "Zero Layout Shift" constraint (ensuring the container size doesn't jitter) and precision on the centering logic. Please fix ensuring strict adherence to the **No Fading** rule.
