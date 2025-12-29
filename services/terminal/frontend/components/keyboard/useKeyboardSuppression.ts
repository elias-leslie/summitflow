import { useCallback, useRef } from "react";

// Type for elements with VirtualKeyboard API (Chrome 94+)
interface VirtualKeyboardElement extends HTMLElement {
  virtualKeyboardPolicy?: "auto" | "manual";
}

interface NavigatorWithVirtualKeyboard extends Navigator {
  virtualKeyboard?: {
    overlaysContent: boolean;
    hide: () => void;
    show: () => void;
  };
}

// Suppression method used (for debugging/logging)
export type SuppressionMethod =
  | "virtualKeyboard" // Chrome 94+ VirtualKeyboard API
  | "passwordHack" // type="password" trick
  | "inputMode" // inputMode="none"
  | "readonly" // readonly attribute
  | "none";

// Check if VirtualKeyboard API is available
function hasVirtualKeyboardAPI(): boolean {
  if (typeof navigator === "undefined") return false;
  return "virtualKeyboard" in navigator;
}

// Get the xterm helper textarea (used for input)
function getXtermTextarea(container: HTMLElement): HTMLTextAreaElement | null {
  return container.querySelector(".xterm-helper-textarea");
}

export function useKeyboardSuppression() {
  const originalStateRef = useRef<{
    inputMode?: string;
    type?: string;
    readOnly?: boolean;
    virtualKeyboardPolicy?: string;
  } | null>(null);

  const suppressionMethodRef = useRef<SuppressionMethod>("none");

  // Suppress the native keyboard using tiered approach
  const suppressKeyboard = useCallback((container: HTMLElement): SuppressionMethod => {
    const textarea = getXtermTextarea(container);
    if (!textarea) {
      console.warn("useKeyboardSuppression: Could not find xterm helper textarea");
      return "none";
    }

    // Save original state for restoration
    originalStateRef.current = {
      inputMode: textarea.inputMode,
      type: textarea.getAttribute("type") || undefined,
      readOnly: textarea.readOnly,
      virtualKeyboardPolicy: (textarea as VirtualKeyboardElement).virtualKeyboardPolicy,
    };

    // Tier 1: VirtualKeyboard API (Chrome 94+, Edge)
    if (hasVirtualKeyboardAPI()) {
      const nav = navigator as NavigatorWithVirtualKeyboard;
      if (nav.virtualKeyboard) {
        nav.virtualKeyboard.overlaysContent = true;
        (textarea as VirtualKeyboardElement).virtualKeyboardPolicy = "manual";
        nav.virtualKeyboard.hide();
        suppressionMethodRef.current = "virtualKeyboard";
        return "virtualKeyboard";
      }
    }

    // Tier 2: Password input hack
    // Some browsers hide keyboard for password fields after initial focus
    try {
      const input = document.createElement("input");
      input.type = "password";
      input.style.position = "absolute";
      input.style.left = "-9999px";
      input.style.opacity = "0";
      container.appendChild(input);
      input.focus();
      setTimeout(() => {
        input.blur();
        container.removeChild(input);
        textarea.focus();
      }, 50);
      // This doesn't fully work but reduces keyboard pop-ups
    } catch {
      // Ignore errors from password hack
    }

    // Tier 3: inputMode="none" (works on Firefox, Safari)
    textarea.inputMode = "none";

    // Tier 4: readonly fallback (least effective)
    textarea.readOnly = true;

    // Determine which method is likely working
    suppressionMethodRef.current = "inputMode";
    return "inputMode";
  }, []);

  // Restore the native keyboard
  const restoreKeyboard = useCallback((container: HTMLElement): void => {
    const textarea = getXtermTextarea(container);
    if (!textarea || !originalStateRef.current) return;

    const { inputMode, readOnly, virtualKeyboardPolicy } = originalStateRef.current;

    // Restore VirtualKeyboard API settings
    if (hasVirtualKeyboardAPI()) {
      const nav = navigator as NavigatorWithVirtualKeyboard;
      if (nav.virtualKeyboard) {
        nav.virtualKeyboard.overlaysContent = false;
        (textarea as VirtualKeyboardElement).virtualKeyboardPolicy =
          (virtualKeyboardPolicy as "auto" | "manual") || "auto";
      }
    }

    // Restore inputMode and readOnly
    textarea.inputMode = inputMode || "";
    textarea.readOnly = readOnly || false;

    originalStateRef.current = null;
    suppressionMethodRef.current = "none";
  }, []);

  return {
    suppressKeyboard,
    restoreKeyboard,
    hasVirtualKeyboardAPI,
    getSuppressionMethod: () => suppressionMethodRef.current,
  };
}
