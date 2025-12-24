"use client";

import { useState, useCallback } from "react";
import { FullKeyboard } from "./FullKeyboard";
import { ControlBar } from "./ControlBar";
import { KeyboardSizePreset, TerminalInputHandler } from "./types";
import { ConnectionStatus } from "../Terminal";

interface MobileKeyboardProps {
  onSend: TerminalInputHandler;
  connectionStatus?: ConnectionStatus;
  onReconnect?: () => void;
  keyboardSize?: KeyboardSizePreset;
}

export function MobileKeyboard({
  onSend,
  connectionStatus = "connected",
  onReconnect,
  keyboardSize = "medium",
}: MobileKeyboardProps) {
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

  return (
    <div className="flex flex-col">
      {/* Control bar with arrows and special keys - always visible */}
      <ControlBar
        onSend={onSend}
        connectionStatus={connectionStatus}
        onReconnect={onReconnect}
        ctrlActive={ctrlActive}
        onCtrlToggle={handleCtrlToggle}
      />
      {/* Full keyboard - always visible (custom keyboard only mode) */}
      <FullKeyboard
        onSend={handleSend}
        keyboardSize={keyboardSize}
      />
    </div>
  );
}
