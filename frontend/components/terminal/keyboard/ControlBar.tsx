"use client";

import { useCallback } from "react";
import { clsx } from "clsx";
import { ChevronDown, ChevronUp } from "lucide-react";
import { KeyboardKey } from "./KeyboardKey";
import { KEY_SEQUENCES } from "./keyMappings";
import { useModifiers } from "./ModifierContext";
import { TerminalInputHandler } from "./types";

interface ControlBarProps {
  onSend: TerminalInputHandler;
  // Modifiers
  ctrlActive?: boolean;
  onCtrlToggle?: () => void;
  // Keyboard minimize
  minimized?: boolean;
  onToggleMinimize?: () => void;
}

export function ControlBar({
  onSend,
  ctrlActive = false,
  onCtrlToggle,
  minimized = false,
  onToggleMinimize,
}: ControlBarProps) {
  // Get shift state from shared modifier context
  const { modifiers, resetModifiers } = useModifiers();
  const shiftActive = modifiers.shift !== "off";

  // Helper to clear modifiers after use
  const clearModifiers = useCallback(() => {
    if (ctrlActive && onCtrlToggle) onCtrlToggle();
    resetModifiers(); // Clear sticky shift from context
  }, [ctrlActive, onCtrlToggle, resetModifiers]);

  // Arrow key handlers - don't clear modifiers for arrows
  const handleArrowLeft = useCallback(() => onSend(KEY_SEQUENCES.ARROW_LEFT), [onSend]);
  const handleArrowUp = useCallback(() => onSend(KEY_SEQUENCES.ARROW_UP), [onSend]);
  const handleArrowDown = useCallback(() => onSend(KEY_SEQUENCES.ARROW_DOWN), [onSend]);
  const handleArrowRight = useCallback(() => onSend(KEY_SEQUENCES.ARROW_RIGHT), [onSend]);

  // Special key handlers
  const handleEsc = useCallback(() => {
    onSend(KEY_SEQUENCES.ESC);
    clearModifiers();
  }, [onSend, clearModifiers]);

  const handleTab = useCallback(() => {
    if (shiftActive) {
      // Shift+Tab (backtab) - reverse tab completion
      onSend('\x1b[Z');
    } else {
      onSend(KEY_SEQUENCES.TAB);
    }
    clearModifiers();
  }, [shiftActive, onSend, clearModifiers]);

  return (
    <div className="flex items-center gap-1 px-2 py-1.5 bg-slate-800 border-t border-slate-700">
      {/* Arrow keys */}
      <div className="flex items-center gap-1">
        <KeyboardKey
          label="←"
          onPress={handleArrowLeft}
          className="w-12 text-xl"
        />
        <KeyboardKey
          label="↑"
          onPress={handleArrowUp}
          className="w-11 text-xl"
        />
        <KeyboardKey
          label="↓"
          onPress={handleArrowDown}
          className="w-11 text-xl"
        />
        <KeyboardKey
          label="→"
          onPress={handleArrowRight}
          className="w-12 text-xl"
        />
      </div>

      {/* Special terminal keys */}
      <div className="flex items-center gap-1 ml-1">
        <KeyboardKey
          label="ESC"
          onPress={handleEsc}
          className="text-sm px-2"
        />
        <KeyboardKey
          label="TAB"
          onPress={handleTab}
          className="text-sm px-2"
        />
        <button
          type="button"
          onClick={onCtrlToggle}
          className={clsx(
            "h-11 px-2.5 rounded-md text-sm font-medium transition-colors",
            ctrlActive
              ? "bg-blue-600 text-white"
              : "bg-slate-700 text-slate-300 hover:bg-slate-600"
          )}
        >
          CTRL
        </button>
      </div>

      {/* Right side - keyboard toggle */}
      {onToggleMinimize && (
        <button
          type="button"
          onClick={onToggleMinimize}
          className={clsx(
            "flex items-center justify-center h-11 w-11 rounded-md transition-colors ml-auto",
            minimized
              ? "bg-phosphor-600 text-white"
              : "bg-slate-700 text-slate-300 hover:bg-slate-600"
          )}
          title={minimized ? "Show keyboard" : "Hide keyboard"}
        >
          {minimized ? <ChevronUp className="w-5 h-5" /> : <ChevronDown className="w-5 h-5" />}
        </button>
      )}
    </div>
  );
}
