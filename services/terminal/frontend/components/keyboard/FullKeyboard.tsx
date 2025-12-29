"use client";

import { useEffect, useRef } from "react";
import Keyboard from "simple-keyboard";
import "simple-keyboard/build/css/index.css";
import { useModifiers } from "./ModifierContext";
import { useKeyboardInput } from "./useKeyboardInput";
import { KEY_SEQUENCES } from "./keyMappings";
import { TerminalInputHandler, KeyboardSizePreset, KEYBOARD_SIZE_HEIGHTS } from "./types";

// Android-like keyboard layout
const layout = {
  default: [
    "1 2 3 4 5 6 7 8 9 0",
    "q w e r t y u i o p",
    "a s d f g h j k l",
    "{shift} z x c v b n m {bksp}",
    "{sym} , {space} . {enter}",
  ],
  shift: [
    "1 2 3 4 5 6 7 8 9 0",
    "Q W E R T Y U I O P",
    "A S D F G H J K L",
    "{shift} Z X C V B N M {bksp}",
    "{sym} , {space} . {enter}",
  ],
  symbols: [
    "! @ # $ % ^ & * ( )",
    "- _ = + [ ] \\ ' / ~",
    "` < > { } : ; \" ?",
    "{shift} € £ ¥ • ° ± § {bksp}",
    "{abc} | {space} , {enter}",
  ],
};

// Button display names
const display = {
  "{bksp}": "⌫",
  "{enter}": "↵",
  "{shift}": "⇧",
  "{space}": " ",
  "{sym}": "?123",
  "{abc}": "ABC",
};

interface FullKeyboardProps {
  onSend: TerminalInputHandler;
  keyboardSize?: KeyboardSizePreset;
}

function FullKeyboardInner({ onSend, keyboardSize = "medium" }: FullKeyboardProps) {
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

  // Initialize simple-keyboard
  useEffect(() => {
    if (!containerRef.current) return;

    // Handler uses refs so it never needs to change
    const handleKeyPress = (button: string) => {
      // Handle special keys
      switch (button) {
        case "{enter}":
          sendRawRef.current(KEY_SEQUENCES.ENTER);
          break;
        case "{bksp}":
          sendRawRef.current(KEY_SEQUENCES.BACKSPACE);
          break;
        case "{space}":
          sendKeyRef.current(" ");
          break;
        case "{shift}":
          toggleModifierRef.current("shift");
          // Toggle shift layout in simple-keyboard
          if (keyboardRef.current) {
            const currentLayout = keyboardRef.current.options.layoutName;
            if (currentLayout === "symbols") {
              // Stay in symbols, just toggle modifier
            } else {
              keyboardRef.current.setOptions({
                layoutName: currentLayout === "shift" ? "default" : "shift",
              });
            }
          }
          break;
        case "{sym}":
          // Switch to symbols layout
          if (keyboardRef.current) {
            keyboardRef.current.setOptions({
              layoutName: "symbols",
            });
          }
          break;
        case "{abc}":
          // Switch back to default layout
          if (keyboardRef.current) {
            keyboardRef.current.setOptions({
              layoutName: "default",
            });
          }
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
      layoutName: "default",
      theme: "hg-theme-default terminal-keyboard-theme",
      mergeDisplay: true,
      physicalKeyboardHighlight: false,
      physicalKeyboardHighlightPress: false,
      disableButtonHold: false,
    });

    keyboardRef.current = keyboard;

    return () => {
      keyboard.destroy();
    };
  }, [keyboardSize]); // Recreate keyboard when size changes

  // Update modifier button styles
  useEffect(() => {
    if (!keyboardRef.current) return;

    // Get button classes based on modifier state
    const shiftClass = modifiers.shift === "sticky"
      ? "modifier-sticky"
      : modifiers.shift === "locked"
        ? "modifier-locked"
        : "";

    // Update button themes
    keyboardRef.current.setOptions({
      buttonTheme: [
        ...(shiftClass ? [{ class: shiftClass, buttons: "{shift}" }] : []),
        { class: "accent-key", buttons: "{shift} {bksp} {enter}" },
        { class: "wide-key", buttons: "{sym} {abc}" },
      ],
    });
  }, [modifiers]);

  return (
    <div className="terminal-keyboard-container bg-slate-800">
      <div ref={containerRef} />
      <style jsx global>{`
        .terminal-keyboard-theme {
          background: #1e293b;
          padding: 6px;
          border-radius: 0;
        }

        .terminal-keyboard-theme .hg-button {
          background: #3f4a5c;
          color: #e2e8f0;
          border: none;
          border-radius: 8px;
          height: ${rowHeight}px;
          min-width: 28px;
          font-size: ${rowHeight <= 36 ? 18 : rowHeight <= 44 ? 20 : 22}px;
          font-weight: 400;
          box-shadow: none;
          flex: 1 1 0;
          display: flex;
          align-items: center;
          justify-content: center;
        }

        .terminal-keyboard-theme .hg-button:active {
          background: #4b5563;
        }

        /* Accent colored keys (shift, backspace, enter) */
        .terminal-keyboard-theme .hg-button.accent-key {
          background: #4a5568;
        }

        .terminal-keyboard-theme .hg-button.accent-key:active {
          background: #5a6578;
        }

        /* Wide keys (sym, abc) */
        .terminal-keyboard-theme .hg-button.wide-key {
          background: #4a5568;
          font-size: ${rowHeight <= 36 ? 14 : rowHeight <= 44 ? 15 : 16}px;
          font-weight: 500;
        }

        /* Larger icons for shift, backspace, enter */
        .terminal-keyboard-theme .hg-button[data-skbtn="{shift}"],
        .terminal-keyboard-theme .hg-button[data-skbtn="{bksp}"],
        .terminal-keyboard-theme .hg-button[data-skbtn="{enter}"] {
          font-size: ${rowHeight <= 36 ? 24 : rowHeight <= 44 ? 26 : 28}px;
        }

        /* Modifier states */
        .terminal-keyboard-theme .hg-button.modifier-sticky {
          background: #4a5568;
          border: 2px solid #60a5fa;
          color: #60a5fa;
        }

        .terminal-keyboard-theme .hg-button.modifier-locked {
          background: #3b82f6;
          color: white;
        }

        .terminal-keyboard-theme .hg-row {
          display: flex;
          flex-direction: row;
          gap: 4px;
          margin-bottom: 6px;
        }

        .terminal-keyboard-theme .hg-row:last-child {
          margin-bottom: 0;
        }

        /* Row 3 (ASDF) - 9 keys, add padding for centering effect */
        .terminal-keyboard-theme .hg-row:nth-child(3) {
          padding-left: 5%;
          padding-right: 5%;
        }

        /* Shift key - wider */
        .terminal-keyboard-theme .hg-button[data-skbtn="{shift}"] {
          flex: 1.5 1 0;
        }

        /* Backspace - wider */
        .terminal-keyboard-theme .hg-button[data-skbtn="{bksp}"] {
          flex: 1.5 1 0;
        }

        /* Symbol/ABC toggle - wider */
        .terminal-keyboard-theme .hg-button[data-skbtn="{sym}"],
        .terminal-keyboard-theme .hg-button[data-skbtn="{abc}"] {
          flex: 1.5 1 0;
        }

        /* Space key - takes most of bottom row */
        .terminal-keyboard-theme .hg-button[data-skbtn="{space}"] {
          flex: 4 1 0;
        }

        /* Enter key - wider */
        .terminal-keyboard-theme .hg-button[data-skbtn="{enter}"] {
          flex: 1.5 1 0;
          background: #4a5568;
        }

        /* Apostrophe and period - normal size */
        .terminal-keyboard-theme .hg-button[data-skbtn="'"],
        .terminal-keyboard-theme .hg-button[data-skbtn="."],
        .terminal-keyboard-theme .hg-button[data-skbtn=","] {
          flex: 1 1 0;
        }
      `}</style>
    </div>
  );
}

export function FullKeyboard(props: FullKeyboardProps) {
  // ModifierProvider is expected to be at parent level (MobileKeyboard)
  return <FullKeyboardInner {...props} />;
}
