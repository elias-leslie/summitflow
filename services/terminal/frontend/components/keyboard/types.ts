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

// Keyboard size presets for mobile
export type KeyboardSizePreset = "small" | "medium" | "large";

// Map size presets to row heights in pixels
export const KEYBOARD_SIZE_HEIGHTS: Record<KeyboardSizePreset, number> = {
  small: 36,
  medium: 44,
  large: 52,
};
