"use client";

import { useCallback, useEffect, useRef } from "react";
import Keyboard from "simple-keyboard";
import "simple-keyboard/build/css/index.css";
import { ModifierProvider, useModifiers } from "./ModifierContext";
import { useKeyboardInput } from "./useKeyboardInput";
import { KEY_SEQUENCES } from "./keyMappings";
import { TerminalInputHandler, KeyboardMode } from "./types";
import { Smartphone } from "lucide-react";

// Terminal-optimized keyboard layout
const layout = {
  default: [
    "{esc} 1 2 3 4 5 6 7 8 9 0 {bksp}",
    "{tab} q w e r t y u i o p {enter}",
    "{ctrl} a s d f g h j k l ; '",
    "{shift} z x c v b n m , . /",
    "{alt} {space} {arrowleft} {arrowup} {arrowdown} {arrowright} {toggle}",
  ],
  shift: [
    "{esc} ! @ # $ % ^ & * ( ) {bksp}",
    "{tab} Q W E R T Y U I O P {enter}",
    "{ctrl} A S D F G H J K L : \"",
    "{shift} Z X C V B N M < > ?",
    "{alt} {space} {arrowleft} {arrowup} {arrowdown} {arrowright} {toggle}",
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
  "{arrowleft}": "←",
  "{arrowup}": "↑",
  "{arrowdown}": "↓",
  "{arrowright}": "→",
  "{toggle}": "📱",
};

interface FullKeyboardProps {
  onSend: TerminalInputHandler;
  onToggleMode?: () => void;
  mode?: KeyboardMode;
}

function FullKeyboardInner({ onSend, onToggleMode, mode = "custom" }: FullKeyboardProps) {
  const keyboardRef = useRef<Keyboard | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const { sendKey, sendRaw, modifiers } = useKeyboardInput({ onSend });
  const { toggleModifier } = useModifiers();

  // Handle key press
  const handleKeyPress = useCallback(
    (button: string) => {
      // Handle special keys
      switch (button) {
        case "{esc}":
          sendRaw(KEY_SEQUENCES.ESC);
          break;
        case "{tab}":
          sendRaw(KEY_SEQUENCES.TAB);
          break;
        case "{enter}":
          sendRaw(KEY_SEQUENCES.ENTER);
          break;
        case "{bksp}":
          sendRaw(KEY_SEQUENCES.BACKSPACE);
          break;
        case "{space}":
          sendKey(" ");
          break;
        case "{arrowleft}":
          sendRaw(KEY_SEQUENCES.ARROW_LEFT);
          break;
        case "{arrowup}":
          sendRaw(KEY_SEQUENCES.ARROW_UP);
          break;
        case "{arrowdown}":
          sendRaw(KEY_SEQUENCES.ARROW_DOWN);
          break;
        case "{arrowright}":
          sendRaw(KEY_SEQUENCES.ARROW_RIGHT);
          break;
        case "{ctrl}":
          toggleModifier("ctrl");
          break;
        case "{shift}":
          toggleModifier("shift");
          // Also toggle shift layout in simple-keyboard
          if (keyboardRef.current) {
            const currentLayout = keyboardRef.current.options.layoutName;
            keyboardRef.current.setOptions({
              layoutName: currentLayout === "shift" ? "default" : "shift",
            });
          }
          break;
        case "{alt}":
          toggleModifier("alt");
          break;
        case "{toggle}":
          onToggleMode?.();
          break;
        default:
          // Regular character
          sendKey(button);
          break;
      }

      // Haptic feedback
      if (typeof navigator !== "undefined" && navigator.vibrate) {
        navigator.vibrate(10);
      }
    },
    [sendKey, sendRaw, toggleModifier, onToggleMode]
  );

  // Initialize simple-keyboard
  useEffect(() => {
    if (!containerRef.current) return;

    const keyboard = new Keyboard(containerRef.current, {
      onKeyPress: handleKeyPress,
      layout,
      display,
      theme: "hg-theme-default terminal-keyboard-theme",
      mergeDisplay: true,
      physicalKeyboardHighlight: false,
      physicalKeyboardHighlightPress: false,
    });

    keyboardRef.current = keyboard;

    return () => {
      keyboard.destroy();
    };
  }, [handleKeyPress]);

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
