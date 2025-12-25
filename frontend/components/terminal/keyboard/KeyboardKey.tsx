"use client";

import { useCallback, useRef } from "react";
import { clsx } from "clsx";
import { ModifierState } from "./types";

interface KeyboardKeyProps {
  label: string;
  onPress: () => void;
  state?: ModifierState;
  width?: number; // Width multiplier (1 = normal, 1.5 = 1.5x width, etc.)
  className?: string;
}

// Provide haptic feedback if available
function vibrate() {
  if (typeof navigator !== "undefined" && navigator.vibrate) {
    navigator.vibrate(10);
  }
}

export function KeyboardKey({
  label,
  onPress,
  state = "off",
  width = 1,
  className,
}: KeyboardKeyProps) {
  // Track if touch event was used to prevent duplicate onClick
  const touchedRef = useRef(false);

  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    e.preventDefault(); // Prevent click from firing
    touchedRef.current = true;
    vibrate();
    onPress();
  }, [onPress]);

  const handleClick = useCallback(() => {
    // Only fire if this wasn't a touch event (for mouse/keyboard fallback)
    if (!touchedRef.current) {
      vibrate();
      onPress();
    }
    // Reset for next interaction
    touchedRef.current = false;
  }, [onPress]);

  return (
    <button
      type="button"
      onTouchStart={handleTouchStart}
      onClick={handleClick}
      className={clsx(
        // Base styles
        "flex items-center justify-center",
        "text-base font-medium",
        "rounded-md",
        "select-none touch-manipulation",
        "transition-colors duration-100",
        // Height
        "h-11 min-h-[44px]",
        // State-based styling
        state === "off" && "bg-slate-700 text-slate-200 active:bg-slate-600",
        state === "sticky" && "bg-slate-700 text-phosphor-400 border border-phosphor-500 active:bg-slate-600",
        state === "locked" && "bg-phosphor-600 text-white active:bg-phosphor-500",
        className
      )}
      style={{
        flex: width,
        minWidth: `${width * 44}px`, // 44px base width
      }}
    >
      {label}
    </button>
  );
}
