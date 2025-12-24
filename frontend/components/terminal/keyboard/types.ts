// Keyboard mode: native Android keyboard + key bar, or full custom keyboard
export type KeyboardMode = "native" | "custom";

// Modifier key states: off, sticky (single-tap, applies to next key), locked (double-tap, persists)
export type ModifierState = "off" | "sticky" | "locked";

// State for all modifier keys
export interface ModifierStates {
  shift: ModifierState;
  ctrl: ModifierState;
  alt: ModifierState;
}

// Configuration for a single key
export interface KeyConfig {
  label: string;
  sequence: string;
  width?: number; // Width multiplier (1 = normal, 1.5 = 1.5x width, etc.)
  isModifier?: boolean;
}

// Terminal input handler type
export type TerminalInputHandler = (sequence: string) => void;
