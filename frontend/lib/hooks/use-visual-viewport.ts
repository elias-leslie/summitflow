"use client";

import { useEffect, useState, useCallback } from "react";

/**
 * Hook to track visual viewport height for mobile keyboard detection.
 *
 * On mobile devices, when the native keyboard opens, the visual viewport shrinks
 * but the layout viewport (which CSS `100vh` uses) stays the same. This causes
 * content to be hidden behind the keyboard.
 *
 * This hook uses the Visual Viewport API to detect the actual visible height
 * and returns it for dynamic sizing.
 *
 * @param enabled - Whether to track the viewport (to avoid unnecessary listeners)
 * @returns Object with viewport height and keyboard visibility state
 *
 * @example
 * ```tsx
 * const { height, isKeyboardVisible } = useVisualViewport(isMobile && keyboardMode === 'native');
 * return <div style={{ height: isKeyboardVisible ? height : '100%' }}>...</div>;
 * ```
 */
export function useVisualViewport(enabled: boolean = true) {
  // Initialize with window.innerHeight if available, otherwise 0
  const [height, setHeight] = useState<number>(
    typeof window !== "undefined" ? window.innerHeight : 0
  );
  const [isKeyboardVisible, setIsKeyboardVisible] = useState(false);

  const updateViewport = useCallback(() => {
    if (typeof window === "undefined") return;

    const visualViewport = window.visualViewport;
    if (visualViewport) {
      const viewportHeight = visualViewport.height;
      const windowHeight = window.innerHeight;

      setHeight(viewportHeight);

      // Keyboard is considered visible if visual viewport is significantly smaller
      // than the window height (more than 150px difference to account for browser UI)
      const heightDiff = windowHeight - viewportHeight;
      setIsKeyboardVisible(heightDiff > 150);
    } else {
      // Fallback for browsers without Visual Viewport API
      setHeight(window.innerHeight);
      setIsKeyboardVisible(false);
    }
  }, []);

  useEffect(() => {
    if (typeof window === "undefined" || !enabled) return;

    // Set initial values
    updateViewport();

    const visualViewport = window.visualViewport;
    if (visualViewport) {
      visualViewport.addEventListener("resize", updateViewport);
      visualViewport.addEventListener("scroll", updateViewport);

      return () => {
        visualViewport.removeEventListener("resize", updateViewport);
        visualViewport.removeEventListener("scroll", updateViewport);
      };
    }

    // Fallback: listen to window resize
    window.addEventListener("resize", updateViewport);
    return () => {
      window.removeEventListener("resize", updateViewport);
    };
  }, [enabled, updateViewport]);

  return { height, isKeyboardVisible };
}
