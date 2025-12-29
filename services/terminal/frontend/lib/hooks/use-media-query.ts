"use client";

import { useEffect, useState } from "react";

/**
 * SSR-safe media query hook.
 *
 * Returns whether the media query matches. Defaults to `defaultValue` on the server
 * and during initial hydration to prevent hydration mismatches.
 *
 * @param query - Media query string (e.g., "(max-width: 767px)")
 * @param defaultValue - Default value for SSR and initial render (default: false)
 * @returns Whether the media query matches
 *
 * @example
 * ```tsx
 * const isMobile = useMediaQuery("(max-width: 767px)");
 * const isDesktop = useMediaQuery("(min-width: 768px)", true);
 * ```
 */
export function useMediaQuery(query: string, defaultValue = false): boolean {
  const [matches, setMatches] = useState(defaultValue);

  useEffect(() => {
    // Only run on client
    if (typeof window === "undefined") return;

    const mediaQuery = window.matchMedia(query);

    // Set initial value
    setMatches(mediaQuery.matches);

    // Listen for changes
    const handler = (event: MediaQueryListEvent) => {
      setMatches(event.matches);
    };

    mediaQuery.addEventListener("change", handler);

    return () => {
      mediaQuery.removeEventListener("change", handler);
    };
  }, [query]);

  return matches;
}

/**
 * Hook to detect mobile viewport.
 * Returns true for screens < 768px.
 * Defaults to false (desktop) on server to prevent layout shift.
 */
export function useIsMobile(): boolean {
  return useMediaQuery("(max-width: 767px)", false);
}

/**
 * Hook to detect desktop viewport.
 * Returns true for screens >= 768px.
 * Defaults to true (desktop) on server to prevent layout shift.
 */
export function useIsDesktop(): boolean {
  return useMediaQuery("(min-width: 768px)", true);
}
