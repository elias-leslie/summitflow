"use client";

import { useState, useCallback, useEffect } from "react";
import { FullKeyboard } from "./FullKeyboard";
import { ControlBar } from "./ControlBar";
import { ModifierProvider } from "./ModifierContext";
import { KeyboardSizePreset, TerminalInputHandler } from "./types";
import { ConnectionStatus } from "../Terminal";

const MINIMIZED_STORAGE_KEY = "terminal-keyboard-minimized";

interface MobileKeyboardProps {
  onSend: TerminalInputHandler;
  connectionStatus?: ConnectionStatus;
  onReconnect?: () => void;
  keyboardSize?: KeyboardSizePreset;
}

export function MobileKeyboard({
  onSend,
  // connectionStatus and onReconnect reserved for future mobile status display
  keyboardSize = "medium",
}: MobileKeyboardProps) {
  const [ctrlActive, setCtrlActive] = useState(false);
  const [minimized, setMinimized] = useState(false);

  // Load minimized state from localStorage
  useEffect(() => {
    const stored = localStorage.getItem(MINIMIZED_STORAGE_KEY);
    if (stored === "true") {
      setMinimized(true);
    }
  }, []);

  // Save minimized state
  const handleToggleMinimize = useCallback(() => {
    setMinimized(prev => {
      const newValue = !prev;
      localStorage.setItem(MINIMIZED_STORAGE_KEY, String(newValue));
      return newValue;
    });
  }, []);

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

  return (
    <ModifierProvider>
      <div className="flex flex-col">
        {/* Control bar with arrows and special keys - always visible */}
        <ControlBar
          onSend={onSend}
          ctrlActive={ctrlActive}
          onCtrlToggle={handleCtrlToggle}
          minimized={minimized}
          onToggleMinimize={handleToggleMinimize}
        />
        {/* Full keyboard - hidden when minimized */}
        {!minimized && (
          <FullKeyboard
            onSend={handleSend}
            keyboardSize={keyboardSize}
          />
        )}
      </div>
    </ModifierProvider>
  );
}
