"use client";

import { useState, useEffect, useCallback } from "react";
import { EssentialKeyBar } from "./EssentialKeyBar";
import { FullKeyboard } from "./FullKeyboard";
import { KeyboardMode, TerminalInputHandler } from "./types";

const STORAGE_KEY = "terminal-keyboard-mode";

interface MobileKeyboardProps {
  onSend: TerminalInputHandler;
  onModeChange?: (mode: KeyboardMode) => void;
}

export function MobileKeyboard({ onSend, onModeChange }: MobileKeyboardProps) {
  const [mode, setMode] = useState<KeyboardMode>("native");
  const [isLoaded, setIsLoaded] = useState(false);

  // Load preference from localStorage on mount
  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "native" || stored === "custom") {
      setMode(stored);
    }
    setIsLoaded(true);
  }, []);

  // Save preference and notify parent on mode change
  useEffect(() => {
    if (isLoaded) {
      localStorage.setItem(STORAGE_KEY, mode);
      onModeChange?.(mode);
    }
  }, [mode, isLoaded, onModeChange]);

  // Toggle between modes
  const handleToggleMode = useCallback(() => {
    setMode((prev) => (prev === "native" ? "custom" : "native"));
  }, []);

  // Don't render until loaded to prevent flash
  if (!isLoaded) {
    return null;
  }

  return mode === "native" ? (
    <EssentialKeyBar onSend={onSend} onToggleMode={handleToggleMode} mode={mode} />
  ) : (
    <FullKeyboard onSend={onSend} onToggleMode={handleToggleMode} mode={mode} />
  );
}

// Hook to get the current keyboard mode for use in parent components
export function useMobileKeyboardMode() {
  const [mode, setMode] = useState<KeyboardMode>("native");

  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "native" || stored === "custom") {
      setMode(stored);
    }

    // Listen for storage changes
    const handleStorage = (e: StorageEvent) => {
      if (e.key === STORAGE_KEY && (e.newValue === "native" || e.newValue === "custom")) {
        setMode(e.newValue);
      }
    };

    window.addEventListener("storage", handleStorage);
    return () => window.removeEventListener("storage", handleStorage);
  }, []);

  return mode;
}
