"use client";

import { createContext, useContext, useCallback, useState, useRef, ReactNode } from "react";
import { ModifierState, ModifierStates } from "./types";

interface ModifierContextValue {
  modifiers: ModifierStates;
  toggleModifier: (key: keyof ModifierStates) => void;
  resetModifiers: () => void;
  isActive: (key: keyof ModifierStates) => boolean;
}

const ModifierContext = createContext<ModifierContextValue | null>(null);

const DOUBLE_TAP_THRESHOLD = 300; // ms

interface ModifierProviderProps {
  children: ReactNode;
}

export function ModifierProvider({ children }: ModifierProviderProps) {
  const [modifiers, setModifiers] = useState<ModifierStates>({
    shift: "off",
    ctrl: "off",
    alt: "off",
  });

  // Track last tap time for double-tap detection
  const lastTapRef = useRef<{ [key: string]: number }>({});

  // Toggle modifier: off -> sticky -> locked -> off
  // Single tap: off -> sticky OR sticky -> off
  // Double tap: off -> locked OR sticky -> locked
  const toggleModifier = useCallback((key: keyof ModifierStates) => {
    const now = Date.now();
    const lastTap = lastTapRef.current[key] || 0;
    const isDoubleTap = now - lastTap < DOUBLE_TAP_THRESHOLD;
    lastTapRef.current[key] = now;

    setModifiers((prev) => {
      const current = prev[key];

      if (isDoubleTap) {
        // Double-tap: toggle lock
        if (current === "locked") {
          return { ...prev, [key]: "off" as ModifierState };
        }
        return { ...prev, [key]: "locked" as ModifierState };
      } else {
        // Single-tap: toggle sticky
        if (current === "off") {
          return { ...prev, [key]: "sticky" as ModifierState };
        } else if (current === "sticky") {
          return { ...prev, [key]: "off" as ModifierState };
        }
        // If locked, single tap doesn't change it
        return prev;
      }
    });
  }, []);

  // Reset sticky modifiers after a key press (locked stays active)
  const resetModifiers = useCallback(() => {
    setModifiers((prev) => {
      const next = { ...prev };
      for (const key of Object.keys(next) as (keyof ModifierStates)[]) {
        if (next[key] === "sticky") {
          next[key] = "off";
        }
      }
      return next;
    });
  }, []);

  // Check if a modifier is active (sticky or locked)
  const isActive = useCallback(
    (key: keyof ModifierStates) => {
      return modifiers[key] !== "off";
    },
    [modifiers]
  );

  return (
    <ModifierContext.Provider
      value={{
        modifiers,
        toggleModifier,
        resetModifiers,
        isActive,
      }}
    >
      {children}
    </ModifierContext.Provider>
  );
}

export function useModifiers() {
  const context = useContext(ModifierContext);
  if (!context) {
    throw new Error("useModifiers must be used within a ModifierProvider");
  }
  return context;
}
