"use client";

import { useState, useEffect, useCallback } from "react";
import { FullKeyboard } from "./FullKeyboard";
import { ControlBar } from "./ControlBar";
import { KeyboardMode, KeyboardSizePreset, TerminalInputHandler } from "./types";
import { ConnectionStatus } from "../Terminal";

const STORAGE_KEY = "terminal-keyboard-mode";

interface MobileKeyboardProps {
  onSend: TerminalInputHandler;
  onModeChange?: (mode: KeyboardMode) => void;
  connectionStatus?: ConnectionStatus;
  onReconnect?: () => void;
  keyboardSize?: KeyboardSizePreset;
}

export function MobileKeyboard({
  onSend,
  onModeChange,
  connectionStatus = "connected",
  onReconnect,
  keyboardSize = "medium",
}: MobileKeyboardProps) {
  const [mode, setMode] = useState<KeyboardMode>("native");
  const [isLoaded, setIsLoaded] = useState(false);
  const [ctrlActive, setCtrlActive] = useState(false);

  // Wrapped onSend that handles CTRL modifier
  const handleSend = useCallback((key: string) => {
    if (ctrlActive && key.length === 1) {
      // Send Ctrl+key sequence (ASCII control codes)
      const char = key.toLowerCase();
      if (char >= 'a' && char <= 'z') {
        const ctrlCode = char.charCodeAt(0) - 96; // a=1, b=2, ..., z=26
        onSend(String.fromCharCode(ctrlCode));
        setCtrlActive(false);
        return;
      }
    }
    onSend(key);
  }, [ctrlActive, onSend]);

  const handleCtrlToggle = useCallback(() => {
    setCtrlActive(prev => !prev);
  }, []);

  // Load keyboard mode from localStorage on mount
  useEffect(() => {
    const storedMode = localStorage.getItem(STORAGE_KEY);
    if (storedMode === "native" || storedMode === "custom") {
      setMode(storedMode);
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
        ctrlActive={ctrlActive}
        onCtrlToggle={handleCtrlToggle}
      />
      {/* Show full keyboard only in custom mode */}
      {mode === "custom" && (
        <FullKeyboard
          onSend={handleSend}
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
