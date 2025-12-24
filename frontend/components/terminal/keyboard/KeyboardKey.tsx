"use client";

import { useCallback } from "react";
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
  const handlePress = useCallback(() => {
    vibrate();
    onPress();
  }, [onPress]);

  return (
    <button
      type="button"
      onTouchStart={handlePress}
      onClick={handlePress}
      className={clsx(
        // Base styles
        "flex items-center justify-center",
        "text-xs font-medium",
        "rounded-md",
        "select-none touch-manipulation",
        "transition-colors duration-100",
        // Height
        "h-9 min-h-[36px]",
        // State-based styling
        state === "off" && "bg-slate-700 text-slate-200 active:bg-slate-600",
        state === "sticky" && "bg-slate-700 text-phosphor-400 border border-phosphor-500 active:bg-slate-600",
        state === "locked" && "bg-phosphor-600 text-white active:bg-phosphor-500",
        className
      )}
      style={{
        flex: width,
        minWidth: `${width * 36}px`, // 36px base width
      }}
    >
      {label}
    </button>
  );
}
