"use client";

import { useCallback, useRef, useState, useEffect } from "react";
import { clsx } from "clsx";
import { Keyboard, RefreshCw, ChevronUp, ChevronDown } from "lucide-react";
import { KeyboardKey } from "./KeyboardKey";
import { KEY_SEQUENCES } from "./keyMappings";
import { KeyboardMode, TerminalInputHandler, KeyboardSizePreset } from "./types";
import { ConnectionStatus } from "../Terminal";

interface ControlBarProps {
  onSend: TerminalInputHandler;
  onToggleMode?: () => void;
  mode?: KeyboardMode;
  connectionStatus?: ConnectionStatus;
  onReconnect?: () => void;
  keyboardSize?: KeyboardSizePreset;
  onKeyboardSizeChange?: (size: KeyboardSizePreset) => void;
  // CTRL modifier
  ctrlActive?: boolean;
  onCtrlToggle?: () => void;
}

export function ControlBar({
  onSend,
  onToggleMode,
  mode = "native",
  connectionStatus = "connected",
  onReconnect,
  keyboardSize = "medium",
  onKeyboardSizeChange,
  ctrlActive = false,
  onCtrlToggle,
}: ControlBarProps) {
  // Arrow key handlers
  const handleArrowLeft = useCallback(() => onSend(KEY_SEQUENCES.ARROW_LEFT), [onSend]);
  const handleArrowUp = useCallback(() => onSend(KEY_SEQUENCES.ARROW_UP), [onSend]);
  const handleArrowDown = useCallback(() => onSend(KEY_SEQUENCES.ARROW_DOWN), [onSend]);
  const handleArrowRight = useCallback(() => onSend(KEY_SEQUENCES.ARROW_RIGHT), [onSend]);

  // Special key handlers
  const handleEsc = useCallback(() => onSend(KEY_SEQUENCES.ESC), [onSend]);
  const handleTab = useCallback(() => onSend(KEY_SEQUENCES.TAB), [onSend]);

  // Get connection status color for refresh button
  const getStatusColor = () => {
    switch (connectionStatus) {
      case "connecting":
        return "text-yellow-400 animate-pulse";
      case "connected":
        return "text-green-400";
      case "disconnected":
      case "error":
      case "timeout":
      case "session_dead":
        return "text-red-400";
      default:
        return "text-slate-400";
    }
  };

  const canReconnect = ["disconnected", "error", "timeout"].includes(connectionStatus);

  // Cycle through keyboard sizes
  const cycleKeyboardSize = useCallback(() => {
    const sizes: KeyboardSizePreset[] = ["small", "medium", "large"];
    const currentIndex = sizes.indexOf(keyboardSize);
    const nextIndex = (currentIndex + 1) % sizes.length;
    onKeyboardSizeChange?.(sizes[nextIndex]);
  }, [keyboardSize, onKeyboardSizeChange]);

  return (
    <div className="flex items-center gap-1 px-2 py-1.5 bg-slate-800 border-t border-slate-700">
      {/* Arrow keys */}
      <div className="flex items-center gap-1">
        <KeyboardKey
          label="←"
          onPress={handleArrowLeft}
          className="w-9"
        />
        <KeyboardKey
          label="↑"
          onPress={handleArrowUp}
          className="w-9"
        />
        <KeyboardKey
          label="↓"
          onPress={handleArrowDown}
          className="w-9"
        />
        <KeyboardKey
          label="→"
          onPress={handleArrowRight}
          className="w-9"
        />
      </div>

      {/* Special terminal keys */}
      <div className="flex items-center gap-1 ml-1">
        <KeyboardKey
          label="ESC"
          onPress={handleEsc}
          className="text-xs px-1.5"
        />
        <KeyboardKey
          label="TAB"
          onPress={handleTab}
          className="text-xs px-1.5"
        />
        <button
          type="button"
          onClick={onCtrlToggle}
          className={clsx(
            "h-9 px-1.5 rounded-md text-xs font-medium transition-colors",
            ctrlActive
              ? "bg-blue-600 text-white"
              : "bg-slate-700 text-slate-300 hover:bg-slate-600"
          )}
        >
          CTRL
        </button>
      </div>

      {/* Right side icons */}
      <div className="flex items-center gap-1 ml-auto">
        {/* Keyboard mode toggle */}
        {onToggleMode && (
          <button
            type="button"
            onClick={onToggleMode}
            className={clsx(
              "flex items-center justify-center h-9 w-9 rounded-md transition-colors",
              mode === "custom"
                ? "bg-phosphor-600 text-white"
                : "bg-slate-700 text-slate-300 hover:bg-slate-600"
            )}
            title={mode === "native" ? "Switch to full keyboard" : "Switch to native keyboard"}
          >
            <Keyboard className="w-4 h-4" />
          </button>
        )}

        {/* Keyboard size toggle - only show when custom keyboard is active */}
        {mode === "custom" && (
          <button
            type="button"
            onClick={cycleKeyboardSize}
            className="flex items-center justify-center h-9 px-2 rounded-md bg-slate-700 text-slate-300 hover:bg-slate-600 transition-colors text-xs font-medium"
            title={`Keyboard size: ${keyboardSize}`}
          >
            {keyboardSize === "small" ? "S" : keyboardSize === "medium" ? "M" : "L"}
          </button>
        )}

        {/* Refresh/Reconnect - colored by status */}
        <button
          type="button"
          onClick={onReconnect}
          disabled={!canReconnect}
          className={clsx(
            "flex items-center justify-center h-9 w-9 rounded-md transition-colors",
            canReconnect
              ? "bg-slate-700 hover:bg-slate-600"
              : "bg-slate-800 cursor-default",
            getStatusColor()
          )}
          title={canReconnect ? "Reconnect" : `Status: ${connectionStatus}`}
        >
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}
