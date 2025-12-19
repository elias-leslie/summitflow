"use client";

import { useCallback, useEffect, useState } from "react";

const STORAGE_KEY_OPEN = "terminal-open";
const STORAGE_KEY_WIDTH = "terminal-width";

const DEFAULT_WIDTH = 40; // 40% default width

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
  const [isInitialized, setIsInitialized] = useState(false);

  // Read from localStorage on mount (client only)
  useEffect(() => {
    if (typeof window === "undefined") return;

    try {
      const storedOpen = localStorage.getItem(STORAGE_KEY_OPEN);
      const storedWidth = localStorage.getItem(STORAGE_KEY_WIDTH);

      if (storedOpen !== null) {
        setIsOpenState(storedOpen === "true");
      }

      if (storedWidth !== null) {
        const parsed = parseFloat(storedWidth);
        if (!isNaN(parsed) && parsed >= 0 && parsed <= 100) {
          setWidthState(parsed);
        }
      }
    } catch {
      // localStorage not available
    }

    setIsInitialized(true);
  }, []);

  // Persist isOpen to localStorage
  const setOpen = useCallback((open: boolean) => {
    setIsOpenState(open);
    try {
      localStorage.setItem(STORAGE_KEY_OPEN, String(open));
    } catch {
      // localStorage not available
    }
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

  return {
    isOpen,
    width,
    setOpen,
    setWidth,
    toggle,
    /** True once state has been read from localStorage */
    isInitialized,
  };
}
