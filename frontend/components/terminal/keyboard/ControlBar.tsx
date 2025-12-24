"use client";

import { useCallback, useRef } from "react";
import { clsx } from "clsx";
import { Keyboard, Settings2, RefreshCw, Minus } from "lucide-react";
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
  onMinimize?: () => void;
  onShowSettings?: () => void;
  keyboardSize?: KeyboardSizePreset;
  onKeyboardSizeChange?: (size: KeyboardSizePreset) => void;
}

export function ControlBar({
  onSend,
  onToggleMode,
  mode = "native",
  connectionStatus = "connected",
  onReconnect,
  onMinimize,
  onShowSettings,
  keyboardSize = "medium",
  onKeyboardSizeChange,
}: ControlBarProps) {
  const showSettingsRef = useRef(false);
  const settingsButtonRef = useRef<HTMLButtonElement>(null);
  const settingsDropdownRef = useRef<HTMLDivElement>(null);

  // Arrow key handlers
  const handleArrowLeft = useCallback(() => onSend(KEY_SEQUENCES.ARROW_LEFT), [onSend]);
  const handleArrowUp = useCallback(() => onSend(KEY_SEQUENCES.ARROW_UP), [onSend]);
  const handleArrowDown = useCallback(() => onSend(KEY_SEQUENCES.ARROW_DOWN), [onSend]);
  const handleArrowRight = useCallback(() => onSend(KEY_SEQUENCES.ARROW_RIGHT), [onSend]);

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

  return (
    <div className="flex items-center gap-1 px-2 py-1.5 bg-slate-800 border-t border-slate-700">
      {/* Arrow keys - take up remaining space */}
      <div className="flex-1 flex items-center gap-1 min-w-0">
        <KeyboardKey
          label="←"
          onPress={handleArrowLeft}
          className="flex-1 min-w-[44px]"
        />
        <KeyboardKey
          label="↑"
          onPress={handleArrowUp}
          className="flex-1 min-w-[44px]"
        />
        <KeyboardKey
          label="↓"
          onPress={handleArrowDown}
          className="flex-1 min-w-[44px]"
        />
        <KeyboardKey
          label="→"
          onPress={handleArrowRight}
          className="flex-1 min-w-[44px]"
        />
      </div>

      {/* Right side icons */}
      <div className="flex items-center gap-1 ml-2">
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

        {/* Settings */}
        {onShowSettings && (
          <button
            ref={settingsButtonRef}
            type="button"
            onClick={onShowSettings}
            className="flex items-center justify-center h-9 w-9 rounded-md bg-slate-700 text-slate-300 hover:bg-slate-600 transition-colors"
            title="Keyboard settings"
          >
            <Settings2 className="w-4 h-4" />
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

        {/* Minimize */}
        {onMinimize && (
          <button
            type="button"
            onClick={onMinimize}
            className="flex items-center justify-center h-9 w-9 rounded-md bg-slate-700 text-slate-300 hover:bg-slate-600 transition-colors"
            title="Minimize terminal"
          >
            <Minus className="w-4 h-4" />
          </button>
        )}
      </div>
    </div>
  );
}
