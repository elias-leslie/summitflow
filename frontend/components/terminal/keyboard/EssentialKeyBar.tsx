"use client";

import { KeyboardKey } from "./KeyboardKey";
import { ModifierProvider, useModifiers } from "./ModifierContext";
import { useKeyboardInput } from "./useKeyboardInput";
import { KEY_SEQUENCES } from "./keyMappings";
import { TerminalInputHandler, KeyboardMode } from "./types";
import { Keyboard } from "lucide-react";

interface EssentialKeyBarProps {
  onSend: TerminalInputHandler;
  onToggleMode?: () => void;
  mode?: KeyboardMode;
}

function EssentialKeyBarInner({ onSend, onToggleMode, mode = "native" }: EssentialKeyBarProps) {
  const { sendRaw } = useKeyboardInput({ onSend });
  const { modifiers, toggleModifier } = useModifiers();

  return (
    <div className="flex items-center gap-1 px-2 py-1.5 bg-slate-800 border-t border-slate-700">
      {/* ESC key */}
      <KeyboardKey label="ESC" onPress={() => sendRaw(KEY_SEQUENCES.ESC)} />

      {/* TAB key */}
      <KeyboardKey label="TAB" onPress={() => sendRaw(KEY_SEQUENCES.TAB)} />

      {/* Shift+TAB key */}
      <KeyboardKey label="⇧TAB" onPress={() => sendRaw(KEY_SEQUENCES.SHIFT_TAB)} />

      {/* Arrow keys */}
      <KeyboardKey label="←" onPress={() => sendRaw(KEY_SEQUENCES.ARROW_LEFT)} />
      <KeyboardKey label="↑" onPress={() => sendRaw(KEY_SEQUENCES.ARROW_UP)} />
      <KeyboardKey label="↓" onPress={() => sendRaw(KEY_SEQUENCES.ARROW_DOWN)} />
      <KeyboardKey label="→" onPress={() => sendRaw(KEY_SEQUENCES.ARROW_RIGHT)} />

      {/* CTRL modifier */}
      <KeyboardKey
        label="CTRL"
        onPress={() => toggleModifier("ctrl")}
        state={modifiers.ctrl}
        width={1.25}
      />

      {/* Mode toggle button */}
      {onToggleMode && (
        <button
          type="button"
          onClick={onToggleMode}
          className="flex items-center justify-center h-9 min-h-[36px] px-2 rounded-md bg-slate-700 text-slate-300 hover:bg-slate-600 transition-colors"
          title={mode === "native" ? "Switch to full keyboard" : "Switch to native keyboard"}
        >
          <Keyboard className="w-4 h-4" />
        </button>
      )}
    </div>
  );
}

export function EssentialKeyBar(props: EssentialKeyBarProps) {
  return (
    <ModifierProvider>
      <EssentialKeyBarInner {...props} />
    </ModifierProvider>
  );
}
