"use client";

import { useCallback, useRef, useMemo } from "react";
import { useClickOutside } from "@/lib/hooks/useClickOutside";
import { clsx } from "clsx";
import { Settings2 } from "lucide-react";
import {
  TERMINAL_FONTS,
  TERMINAL_FONT_SIZES,
  TerminalFontId,
  TerminalFontSize,
} from "@/lib/hooks/use-terminal-settings";

// Keyboard size type
export type KeyboardSizePreset = "small" | "medium" | "large";

export interface SettingsDropdownProps {
  fontId: TerminalFontId;
  fontSize: TerminalFontSize;
  setFontId: (id: TerminalFontId) => void;
  setFontSize: (size: TerminalFontSize) => void;
  showSettings: boolean;
  setShowSettings: (show: boolean) => void;
  // Keyboard size (only shown on mobile)
  keyboardSize?: KeyboardSizePreset;
  setKeyboardSize?: (size: KeyboardSizePreset) => void;
  isMobile?: boolean;
}

export function SettingsDropdown({
  fontId,
  fontSize,
  setFontId,
  setFontSize,
  showSettings,
  setShowSettings,
  keyboardSize,
  setKeyboardSize,
  isMobile,
}: SettingsDropdownProps) {
  const buttonRef = useRef<HTMLButtonElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const closeDropdown = useCallback(
    () => setShowSettings(false),
    [setShowSettings]
  );
  const clickOutsideRefs = useMemo(() => [buttonRef, dropdownRef], []);

  // Close dropdown when clicking outside
  useClickOutside(clickOutsideRefs, closeDropdown, showSettings);

  // Calculate dropdown position
  const getDropdownStyle = (): React.CSSProperties => {
    if (!buttonRef.current) return {};
    const rect = buttonRef.current.getBoundingClientRect();
    return {
      position: "fixed",
      right: window.innerWidth - rect.right,
      bottom: window.innerHeight - rect.top + 4,
      zIndex: 9999,
    };
  };

  return (
    <div className="relative ml-2">
      <button
        ref={buttonRef}
        onClick={() => setShowSettings(!showSettings)}
        title="Terminal settings"
        className={clsx(
          "p-1.5 rounded transition-colors",
          showSettings
            ? "bg-slate-700 text-phosphor-400"
            : "text-slate-400 hover:text-white hover:bg-slate-700/50"
        )}
      >
        <Settings2 className="w-4 h-4" />
      </button>

      {/* Settings dropdown - fixed position to escape overflow */}
      {showSettings && (
        <div
          ref={dropdownRef}
          style={getDropdownStyle()}
          className="bg-slate-800 border border-slate-700 rounded-lg shadow-xl p-3 min-w-[200px]"
        >
          {/* Font family */}
          <div className="mb-3">
            <label className="block text-xs text-slate-400 mb-1">Font</label>
            <select
              value={fontId}
              onChange={(e) => setFontId(e.target.value as TerminalFontId)}
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
          <div className={isMobile && keyboardSize !== undefined ? "mb-3" : ""}>
            <label className="block text-xs text-slate-400 mb-1">Size</label>
            <select
              value={fontSize}
              onChange={(e) =>
                setFontSize(Number(e.target.value) as TerminalFontSize)
              }
              className="w-full px-2 py-1.5 text-sm bg-slate-900 border border-slate-700 rounded text-slate-200 focus:outline-none focus:border-phosphor-500"
            >
              {TERMINAL_FONT_SIZES.map((size) => (
                <option key={size} value={size}>
                  {size}px
                </option>
              ))}
            </select>
          </div>

          {/* Keyboard size - only on mobile */}
          {isMobile && keyboardSize !== undefined && setKeyboardSize && (
            <div>
              <label className="block text-xs text-slate-400 mb-1">
                Keyboard Size
              </label>
              <div className="flex gap-1">
                {(["small", "medium", "large"] as const).map((size) => (
                  <button
                    key={size}
                    type="button"
                    onClick={() => setKeyboardSize(size)}
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
          )}
        </div>
      )}
    </div>
  );
}
