"use client";

import { useCallback, useEffect, useState } from "react";

const STORAGE_KEY_WIDTH = "terminal-width";
const STORAGE_KEY_LAYOUT_MODE = "terminal-layout-mode";
const STORAGE_KEY_PANE_SIZES = "terminal-pane-sizes";
const STORAGE_KEY_PANE_SESSIONS = "terminal-pane-sessions";

const DEFAULT_WIDTH = 40; // 40% default width

export type LayoutMode = "single" | "horizontal" | "vertical";

const DEFAULT_LAYOUT_MODE: LayoutMode = "single";
const DEFAULT_PANE_SIZES = [50, 50]; // Equal split for two panes

/**
 * Hook for managing terminal panel UI state with localStorage persistence.
 *
 * State is persisted to localStorage so it survives page navigation and refresh.
 * SSR-safe: reads from localStorage only on client.
 *
 * @returns Terminal state and setters
 *
 * @example
 * ```tsx
 * const { isOpen, width, toggle, setWidth } = useTerminalState();
 *
 * return (
 *   <PanelGroup>
 *     <Panel>{children}</Panel>
 *     {isOpen && (
 *       <>
 *         <PanelResizeHandle />
 *         <Panel defaultSize={width} onResize={setWidth}>
 *           <TerminalTabs />
 *         </Panel>
 *       </>
 *     )}
 *   </PanelGroup>
 * );
 * ```
 */
export function useTerminalState() {
  // Default to closed on initial render (SSR-safe)
  const [isOpen, setIsOpenState] = useState(false);
  const [width, setWidthState] = useState(DEFAULT_WIDTH);
  const [layoutMode, setLayoutModeState] = useState<LayoutMode>(DEFAULT_LAYOUT_MODE);
  const [paneSizes, setPaneSizesState] = useState<number[]>(DEFAULT_PANE_SIZES);
  const [paneSessions, setPaneSessionsState] = useState<string[]>([]);
  const [isInitialized, setIsInitialized] = useState(false);

  // Read from localStorage on mount (client only)
  // NOTE: isOpen is NOT restored - terminal always starts closed on page load
  // Sessions persist on server, user clicks button to reveal them
  useEffect(() => {
    if (typeof window === "undefined") return;

    try {
      // Don't restore isOpen - always start closed
      const storedWidth = localStorage.getItem(STORAGE_KEY_WIDTH);
      const storedLayoutMode = localStorage.getItem(STORAGE_KEY_LAYOUT_MODE);
      const storedPaneSizes = localStorage.getItem(STORAGE_KEY_PANE_SIZES);
      const storedPaneSessions = localStorage.getItem(STORAGE_KEY_PANE_SESSIONS);

      if (storedWidth !== null) {
        const parsed = parseFloat(storedWidth);
        if (!isNaN(parsed) && parsed >= 0 && parsed <= 100) {
          setWidthState(parsed);
        }
      }

      if (storedLayoutMode !== null) {
        if (["single", "horizontal", "vertical"].includes(storedLayoutMode)) {
          setLayoutModeState(storedLayoutMode as LayoutMode);
        }
      }

      if (storedPaneSizes !== null) {
        const parsed = JSON.parse(storedPaneSizes);
        if (Array.isArray(parsed) && parsed.every((n) => typeof n === "number")) {
          setPaneSizesState(parsed);
        }
      }

      if (storedPaneSessions !== null) {
        const parsed = JSON.parse(storedPaneSessions);
        if (Array.isArray(parsed) && parsed.every((s) => typeof s === "string")) {
          setPaneSessionsState(parsed);
        }
      }
    } catch {
      // localStorage not available or parse error
    }

    setIsInitialized(true);
  }, []);

  // Set open state (not persisted - terminal starts closed on page load)
  const setOpen = useCallback((open: boolean) => {
    setIsOpenState(open);
  }, []);

  // Persist width to localStorage
  const setWidth = useCallback((newWidth: number) => {
    setWidthState(newWidth);
    try {
      localStorage.setItem(STORAGE_KEY_WIDTH, String(newWidth));
    } catch {
      // localStorage not available
    }
  }, []);

  // Toggle open state
  const toggle = useCallback(() => {
    setOpen(!isOpen);
  }, [isOpen, setOpen]);

  // Persist layoutMode to localStorage
  const setLayoutMode = useCallback((mode: LayoutMode) => {
    setLayoutModeState(mode);
    try {
      localStorage.setItem(STORAGE_KEY_LAYOUT_MODE, mode);
    } catch {
      // localStorage not available
    }
  }, []);

  // Persist paneSizes to localStorage
  const setPaneSizes = useCallback((sizes: number[]) => {
    setPaneSizesState(sizes);
    try {
      localStorage.setItem(STORAGE_KEY_PANE_SIZES, JSON.stringify(sizes));
    } catch {
      // localStorage not available
    }
  }, []);

  // Persist paneSessions to localStorage
  const setPaneSessions = useCallback((sessions: string[]) => {
    setPaneSessionsState(sessions);
    try {
      localStorage.setItem(STORAGE_KEY_PANE_SESSIONS, JSON.stringify(sessions));
    } catch {
      // localStorage not available
    }
  }, []);

  return {
    isOpen,
    width,
    layoutMode,
    paneSizes,
    paneSessions,
    setOpen,
    setWidth,
    setLayoutMode,
    setPaneSizes,
    setPaneSessions,
    toggle,
    /** True once state has been read from localStorage */
    isInitialized,
  };
}
