"use client";

import { useCallback, useRef, useState, useEffect } from "react";
import { clsx } from "clsx";
import { Keyboard, Settings2, RefreshCw, Minus } from "lucide-react";
import { KeyboardKey } from "./KeyboardKey";
import { KEY_SEQUENCES } from "./keyMappings";
import { KeyboardMode, TerminalInputHandler, KeyboardSizePreset } from "./types";
import { ConnectionStatus } from "../Terminal";
import {
  TERMINAL_FONTS,
  TERMINAL_FONT_SIZES,
  TerminalFontId,
  TerminalFontSize,
} from "@/lib/hooks/use-terminal-settings";

interface ControlBarProps {
  onSend: TerminalInputHandler;
  onToggleMode?: () => void;
  mode?: KeyboardMode;
  connectionStatus?: ConnectionStatus;
  onReconnect?: () => void;
  onMinimize?: () => void;
  keyboardSize?: KeyboardSizePreset;
  onKeyboardSizeChange?: (size: KeyboardSizePreset) => void;
  // Font settings
  fontId?: TerminalFontId;
  fontSize?: TerminalFontSize;
  onFontIdChange?: (id: TerminalFontId) => void;
  onFontSizeChange?: (size: TerminalFontSize) => void;
}

export function ControlBar({
  onSend,
  onToggleMode,
  mode = "native",
  connectionStatus = "connected",
  onReconnect,
  onMinimize,
  keyboardSize = "medium",
  onKeyboardSizeChange,
  fontId = "jetbrains-mono",
  fontSize = 14,
  onFontIdChange,
  onFontSizeChange,
}: ControlBarProps) {
  const [showSettings, setShowSettings] = useState(false);
  const settingsButtonRef = useRef<HTMLButtonElement>(null);
  const settingsDropdownRef = useRef<HTMLDivElement>(null);

  // Close settings when clicking outside
  useEffect(() => {
    if (!showSettings) return;

    const handleClickOutside = (e: MouseEvent | TouchEvent) => {
      if (
        settingsButtonRef.current &&
        !settingsButtonRef.current.contains(e.target as Node) &&
        settingsDropdownRef.current &&
        !settingsDropdownRef.current.contains(e.target as Node)
      ) {
        setShowSettings(false);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    document.addEventListener("touchstart", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("touchstart", handleClickOutside);
    };
  }, [showSettings]);

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

  // Handle keyboard size change with proper event stopping
  const handleSizeChange = useCallback((e: React.MouseEvent | React.TouchEvent, size: KeyboardSizePreset) => {
    e.preventDefault();
    e.stopPropagation();
    onKeyboardSizeChange?.(size);
    setShowSettings(false);
  }, [onKeyboardSizeChange]);

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

        {/* Settings with dropdown */}
        <div className="relative">
          <button
            ref={settingsButtonRef}
            type="button"
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              setShowSettings(!showSettings);
            }}
            className={clsx(
              "flex items-center justify-center h-9 w-9 rounded-md transition-colors",
              showSettings
                ? "bg-phosphor-600 text-white"
                : "bg-slate-700 text-slate-300 hover:bg-slate-600"
            )}
            title="Terminal settings"
          >
            <Settings2 className="w-4 h-4" />
          </button>

          {/* Settings dropdown - using fixed positioning to avoid keyboard interference */}
          {showSettings && (
            <div
              ref={settingsDropdownRef}
              className="fixed bg-slate-800 border border-slate-700 rounded-lg shadow-xl p-3 min-w-[200px] z-[9999]"
              style={{
                bottom: settingsButtonRef.current
                  ? window.innerHeight - settingsButtonRef.current.getBoundingClientRect().top + 8
                  : "auto",
                right: settingsButtonRef.current
                  ? window.innerWidth - settingsButtonRef.current.getBoundingClientRect().right
                  : "auto",
              }}
              onClick={(e) => e.stopPropagation()}
              onTouchStart={(e) => e.stopPropagation()}
            >
              {/* Font family */}
              <div className="mb-3">
                <label className="block text-xs text-slate-400 mb-1">Font</label>
                <select
                  value={fontId}
                  onChange={(e) => {
                    e.stopPropagation();
                    onFontIdChange?.(e.target.value as TerminalFontId);
                  }}
                  onClick={(e) => e.stopPropagation()}
                  className="w-full px-2 py-1.5 text-sm bg-slate-900 border border-slate-700 rounded text-slate-200 focus:outline-none focus:border-phosphor-500"
                >
                  {TERMINAL_FONTS.map((font) => (
                    <option key={font.id} value={font.id}>
                      {font.name}
                    </option>
                  ))}
                </select>
              </div>

              {/* Font size */}
              <div className="mb-3">
                <label className="block text-xs text-slate-400 mb-1">Font Size</label>
                <select
                  value={fontSize}
                  onChange={(e) => {
                    e.stopPropagation();
                    onFontSizeChange?.(Number(e.target.value) as TerminalFontSize);
                  }}
                  onClick={(e) => e.stopPropagation()}
                  className="w-full px-2 py-1.5 text-sm bg-slate-900 border border-slate-700 rounded text-slate-200 focus:outline-none focus:border-phosphor-500"
                >
                  {TERMINAL_FONT_SIZES.map((size) => (
                    <option key={size} value={size}>
                      {size}px
                    </option>
                  ))}
                </select>
              </div>

              {/* Keyboard size */}
              <div>
                <label className="block text-xs text-slate-400 mb-1">Keyboard Size</label>
                <div className="flex gap-1">
                  {(["small", "medium", "large"] as const).map((size) => (
                    <button
                      key={size}
                      type="button"
                      onClick={(e) => handleSizeChange(e, size)}
                      onTouchStart={(e) => {
                        e.stopPropagation();
                      }}
                      className={clsx(
                        "flex-1 px-2 py-1.5 text-xs rounded transition-colors capitalize",
                        keyboardSize === size
                          ? "bg-phosphor-600 text-white"
                          : "bg-slate-700 text-slate-300 hover:bg-slate-600"
                      )}
                    >
                      {size}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>

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
