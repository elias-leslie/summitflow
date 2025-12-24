"use client";

import { useState, useEffect, useCallback } from "react";
import { EssentialKeyBar } from "./EssentialKeyBar";
import { FullKeyboard } from "./FullKeyboard";
import { ControlBar } from "./ControlBar";
import { KeyboardMode, KeyboardSizePreset, TerminalInputHandler } from "./types";
import { ConnectionStatus } from "../Terminal";

const STORAGE_KEY = "terminal-keyboard-mode";
const SIZE_STORAGE_KEY = "terminal-keyboard-size";

interface MobileKeyboardProps {
  onSend: TerminalInputHandler;
  onModeChange?: (mode: KeyboardMode) => void;
  connectionStatus?: ConnectionStatus;
  onReconnect?: () => void;
  onMinimize?: () => void;
}

export function MobileKeyboard({
  onSend,
  onModeChange,
  connectionStatus = "connected",
  onReconnect,
  onMinimize,
}: MobileKeyboardProps) {
  const [mode, setMode] = useState<KeyboardMode>("native");
  const [keyboardSize, setKeyboardSize] = useState<KeyboardSizePreset>("medium");
  const [isLoaded, setIsLoaded] = useState(false);

  // Load preferences from localStorage on mount
  useEffect(() => {
    const storedMode = localStorage.getItem(STORAGE_KEY);
    if (storedMode === "native" || storedMode === "custom") {
      setMode(storedMode);
    }
    const storedSize = localStorage.getItem(SIZE_STORAGE_KEY);
    if (storedSize === "small" || storedSize === "medium" || storedSize === "large") {
      setKeyboardSize(storedSize);
    }
    setIsLoaded(true);
  }, []);

  // Save mode preference and notify parent on mode change
  useEffect(() => {
    if (isLoaded) {
      localStorage.setItem(STORAGE_KEY, mode);
      onModeChange?.(mode);
    }
  }, [mode, isLoaded, onModeChange]);

  // Save keyboard size preference
  const handleKeyboardSizeChange = useCallback((size: KeyboardSizePreset) => {
    setKeyboardSize(size);
    localStorage.setItem(SIZE_STORAGE_KEY, size);
  }, []);

  // Toggle between modes
  const handleToggleMode = useCallback(() => {
    setMode((prev) => (prev === "native" ? "custom" : "native"));
  }, []);

  // Don't render until loaded to prevent flash
  if (!isLoaded) {
    return null;
  }

  return (
    <div className="flex flex-col">
      {/* Control bar with arrows and icons - always visible */}
      <ControlBar
        onSend={onSend}
        onToggleMode={handleToggleMode}
        mode={mode}
        connectionStatus={connectionStatus}
        onReconnect={onReconnect}
        onMinimize={onMinimize}
        keyboardSize={keyboardSize}
        onKeyboardSizeChange={handleKeyboardSizeChange}
      />
      {/* Show full keyboard only in custom mode */}
      {mode === "custom" && (
        <FullKeyboard
          onSend={onSend}
          mode={mode}
          keyboardSize={keyboardSize}
        />
      )}
    </div>
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
