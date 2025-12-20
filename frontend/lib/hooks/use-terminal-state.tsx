"use client";

import { createContext, useCallback, useContext, useEffect, useState, ReactNode } from "react";

const STORAGE_KEY_WIDTH = "terminal-width";
const STORAGE_KEY_LAYOUT_MODE = "terminal-layout-mode";
const STORAGE_KEY_PANE_SIZES = "terminal-pane-sizes";
const STORAGE_KEY_PANE_SESSIONS = "terminal-pane-sessions";

const DEFAULT_WIDTH = 40; // 40% default width

export type LayoutMode = "single" | "horizontal" | "vertical";

const DEFAULT_LAYOUT_MODE: LayoutMode = "single";
const DEFAULT_PANE_SIZES = [50, 50]; // Equal split for two panes

// Context type
interface TerminalStateContextType {
  isOpen: boolean;
  width: number;
  layoutMode: LayoutMode;
  paneSizes: number[];
  paneSessions: string[];
  setOpen: (open: boolean) => void;
  setWidth: (width: number) => void;
  setLayoutMode: (mode: LayoutMode) => void;
  setPaneSizes: (sizes: number[]) => void;
  setPaneSessions: (sessions: string[]) => void;
  toggle: () => void;
  isInitialized: boolean;
}

const TerminalStateContext = createContext<TerminalStateContextType | null>(null);

/**
 * Provider for terminal state. Wrap your app with this to share terminal state.
 */
export function TerminalStateProvider({ children }: { children: ReactNode }) {
  // Default to closed on initial render (SSR-safe)
  const [isOpen, setIsOpenState] = useState(false);
  const [width, setWidthState] = useState(DEFAULT_WIDTH);
  const [layoutMode, setLayoutModeState] = useState<LayoutMode>(DEFAULT_LAYOUT_MODE);
  const [paneSizes, setPaneSizesState] = useState<number[]>(DEFAULT_PANE_SIZES);
  const [paneSessions, setPaneSessionsState] = useState<string[]>([]);
  const [isInitialized, setIsInitialized] = useState(false);

  // Read from localStorage on mount (client only)
  // NOTE: isOpen is NOT restored - terminal always starts closed on page load
  useEffect(() => {
    if (typeof window === "undefined") return;

    try {
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
    setIsOpenState((prev) => !prev);
  }, []);

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

  const value: TerminalStateContextType = {
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
    isInitialized,
  };

  return (
    <TerminalStateContext.Provider value={value}>
      {children}
    </TerminalStateContext.Provider>
  );
}

/**
 * Hook for accessing terminal panel UI state.
 * Must be used within a TerminalStateProvider.
 */
export function useTerminalState(): TerminalStateContextType {
  const context = useContext(TerminalStateContext);
  if (!context) {
    throw new Error("useTerminalState must be used within a TerminalStateProvider");
  }
  return context;
}
