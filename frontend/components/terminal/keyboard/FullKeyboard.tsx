"use client";

import { useEffect, useRef } from "react";
import Keyboard from "simple-keyboard";
import "simple-keyboard/build/css/index.css";
import { ModifierProvider, useModifiers } from "./ModifierContext";
import { useKeyboardInput } from "./useKeyboardInput";
import { KEY_SEQUENCES } from "./keyMappings";
import { TerminalInputHandler, KeyboardMode, KeyboardSizePreset, KEYBOARD_SIZE_HEIGHTS } from "./types";

// Terminal-optimized keyboard layout - arrows moved to control bar
const layout = {
  default: [
    "{esc} 1 2 3 4 5 6 7 8 9 0 {bksp}",
    "{tab} q w e r t y u i o p",
    "{ctrl} a s d f g h j k l ; '",
    "{shift} z x c v b n m , . / {alt}",
    "{space} {enter}",
  ],
  shift: [
    "{esc} ! @ # $ % ^ & * ( ) {bksp}",
    "{tab} Q W E R T Y U I O P",
    "{ctrl} A S D F G H J K L : \"",
    "{shift} Z X C V B N M < > ? {alt}",
    "{space} {enter}",
  ],
};

// Button display names
const display = {
  "{esc}": "ESC",
  "{bksp}": "⌫",
  "{tab}": "TAB",
  "{enter}": "↵",
  "{ctrl}": "CTRL",
  "{shift}": "SHIFT",
  "{alt}": "ALT",
  "{space}": "SPACE",
};

interface FullKeyboardProps {
  onSend: TerminalInputHandler;
  onToggleMode?: () => void;
  mode?: KeyboardMode;
  keyboardSize?: KeyboardSizePreset;
}

function FullKeyboardInner({ onSend, onToggleMode, mode = "custom", keyboardSize = "medium" }: FullKeyboardProps) {
  const keyboardRef = useRef<Keyboard | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const { sendKey, sendRaw, modifiers } = useKeyboardInput({ onSend });
  const { toggleModifier } = useModifiers();

  // Get row height based on size preset
  const rowHeight = KEYBOARD_SIZE_HEIGHTS[keyboardSize];

  // Store callbacks in refs to avoid recreating keyboard on every change
  const sendKeyRef = useRef(sendKey);
  const sendRawRef = useRef(sendRaw);
  const toggleModifierRef = useRef(toggleModifier);

  // Keep refs updated
  useEffect(() => {
    sendKeyRef.current = sendKey;
    sendRawRef.current = sendRaw;
    toggleModifierRef.current = toggleModifier;
  }, [sendKey, sendRaw, toggleModifier]);

  // Initialize simple-keyboard ONCE (no dependencies that change)
  useEffect(() => {
    if (!containerRef.current) return;

    // Handler uses refs so it never needs to change
    const handleKeyPress = (button: string) => {
      // Handle special keys
      switch (button) {
        case "{esc}":
          sendRawRef.current(KEY_SEQUENCES.ESC);
          break;
        case "{tab}":
          sendRawRef.current(KEY_SEQUENCES.TAB);
          break;
        case "{enter}":
          sendRawRef.current(KEY_SEQUENCES.ENTER);
          break;
        case "{bksp}":
          sendRawRef.current(KEY_SEQUENCES.BACKSPACE);
          break;
        case "{space}":
          sendKeyRef.current(" ");
          break;
        case "{ctrl}":
          toggleModifierRef.current("ctrl");
          break;
        case "{shift}":
          toggleModifierRef.current("shift");
          // Also toggle shift layout in simple-keyboard
          if (keyboardRef.current) {
            const currentLayout = keyboardRef.current.options.layoutName;
            keyboardRef.current.setOptions({
              layoutName: currentLayout === "shift" ? "default" : "shift",
            });
          }
          break;
        case "{alt}":
          toggleModifierRef.current("alt");
          break;
        default:
          // Regular character
          sendKeyRef.current(button);
          break;
      }

      // Haptic feedback
      if (typeof navigator !== "undefined" && navigator.vibrate) {
        navigator.vibrate(10);
      }
    };

    const keyboard = new Keyboard(containerRef.current, {
      onKeyPress: handleKeyPress,
      layout,
      display,
      theme: "hg-theme-default terminal-keyboard-theme",
      mergeDisplay: true,
      physicalKeyboardHighlight: false,
      physicalKeyboardHighlightPress: false,
      // Disable key repeat/hold behavior
      disableButtonHold: true,
    });

    keyboardRef.current = keyboard;

    return () => {
      keyboard.destroy();
    };
  }, []); // Empty deps - only initialize once

  // Update modifier button styles
  useEffect(() => {
    if (!keyboardRef.current) return;

    // Get button classes based on modifier state
    const getButtonClass = (mod: keyof typeof modifiers) => {
      switch (modifiers[mod]) {
        case "sticky":
          return "modifier-sticky";
        case "locked":
          return "modifier-locked";
        default:
          return "";
      }
    };

    // Update button themes
    keyboardRef.current.setOptions({
      buttonTheme: [
        {
          class: getButtonClass("ctrl"),
          buttons: "{ctrl}",
        },
        {
          class: getButtonClass("shift"),
          buttons: "{shift}",
        },
        {
          class: getButtonClass("alt"),
          buttons: "{alt}",
        },
      ].filter((t) => t.class),
    });
  }, [modifiers]);

  return (
    <div className="terminal-keyboard-container bg-slate-800 border-t border-slate-700">
      <div ref={containerRef} />
      <style jsx global>{`
        .terminal-keyboard-theme {
          background: #1e293b;
          padding: 4px;
          border-radius: 0;
        }

        .terminal-keyboard-theme .hg-button {
          background: #334155;
          color: #e2e8f0;
          border: none;
          border-radius: 4px;
          height: 36px;
          font-size: 12px;
          box-shadow: none;
        }

        .terminal-keyboard-theme .hg-button:active {
          background: #475569;
        }

        .terminal-keyboard-theme .hg-button.modifier-sticky {
          border: 1px solid #22c55e;
          color: #4ade80;
        }

        .terminal-keyboard-theme .hg-button.modifier-locked {
          background: #16a34a;
          color: white;
        }

        .terminal-keyboard-theme .hg-row {
          margin-bottom: 4px;
        }

        .terminal-keyboard-theme .hg-row:last-child {
          margin-bottom: 0;
        }
      `}</style>
    </div>
  );
}

export function FullKeyboard(props: FullKeyboardProps) {
  return (
    <ModifierProvider>
      <FullKeyboardInner {...props} />
    </ModifierProvider>
  );
}
