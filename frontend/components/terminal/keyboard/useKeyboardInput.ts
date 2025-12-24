import { useCallback } from "react";
import { useModifiers } from "./ModifierContext";
import { withCtrl, withShift } from "./keyMappings";
import { TerminalInputHandler } from "./types";

interface UseKeyboardInputProps {
  onSend: TerminalInputHandler;
}

export function useKeyboardInput({ onSend }: UseKeyboardInputProps) {
  const { modifiers, resetModifiers, isActive } = useModifiers();

  // Send a key sequence to the terminal, applying active modifiers
  const sendKey = useCallback(
    (sequence: string) => {
      let finalSequence = sequence;

      // Apply Ctrl modifier to single characters
      if (isActive("ctrl") && sequence.length === 1) {
        finalSequence = withCtrl(sequence);
      }

      // Apply Shift modifier to single characters
      if (isActive("shift") && sequence.length === 1) {
        finalSequence = withShift(finalSequence);
      }

      // Send to terminal
      onSend(finalSequence);

      // Reset sticky modifiers after key press
      resetModifiers();
    },
    [onSend, isActive, resetModifiers]
  );

  // Send a raw sequence without modifier processing (for special keys)
  const sendRaw = useCallback(
    (sequence: string) => {
      onSend(sequence);
      resetModifiers();
    },
    [onSend, resetModifiers]
  );

  return {
    sendKey,
    sendRaw,
    modifiers,
    isActive,
  };
}
