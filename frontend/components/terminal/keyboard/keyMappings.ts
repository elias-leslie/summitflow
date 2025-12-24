// Terminal escape sequences for special keys
export const KEY_SEQUENCES = {
  // Control keys
  ESC: "\x1b",
  TAB: "\t",
  SHIFT_TAB: "\x1b[Z",
  ENTER: "\r",
  BACKSPACE: "\x7f",
  DELETE: "\x1b[3~",

  // Arrow keys (ANSI escape sequences)
  ARROW_UP: "\x1b[A",
  ARROW_DOWN: "\x1b[B",
  ARROW_RIGHT: "\x1b[C",
  ARROW_LEFT: "\x1b[D",

  // Navigation keys
  HOME: "\x1b[H",
  END: "\x1b[F",
  PAGE_UP: "\x1b[5~",
  PAGE_DOWN: "\x1b[6~",

  // Function keys
  F1: "\x1bOP",
  F2: "\x1bOQ",
  F3: "\x1bOR",
  F4: "\x1bOS",
  F5: "\x1b[15~",
  F6: "\x1b[17~",
  F7: "\x1b[18~",
  F8: "\x1b[19~",
  F9: "\x1b[20~",
  F10: "\x1b[21~",
  F11: "\x1b[23~",
  F12: "\x1b[24~",
} as const;

// Generate Ctrl+key sequence (Ctrl+A = 0x01, Ctrl+B = 0x02, etc.)
export function withCtrl(char: string): string {
  const code = char.toLowerCase().charCodeAt(0);
  // Ctrl key subtracts 96 from the ASCII code (a=97 -> 1, b=98 -> 2, etc.)
  if (code >= 97 && code <= 122) {
    return String.fromCharCode(code - 96);
  }
  // Special cases
  if (char === "[" || char === "3") return "\x1b"; // Ctrl+[ or Ctrl+3 = ESC
  if (char === "\\") return "\x1c";
  if (char === "]") return "\x1d";
  if (char === "^" || char === "6") return "\x1e";
  if (char === "_" || char === "-") return "\x1f";
  if (char === " " || char === "2") return "\x00"; // Ctrl+Space or Ctrl+2 = NUL
  return char;
}

// Shift character mapping (lowercase -> uppercase, special chars)
export function withShift(char: string): string {
  // Letters
  if (char >= "a" && char <= "z") {
    return char.toUpperCase();
  }
  // Numbers to symbols
  const numberShifts: Record<string, string> = {
    "1": "!",
    "2": "@",
    "3": "#",
    "4": "$",
    "5": "%",
    "6": "^",
    "7": "&",
    "8": "*",
    "9": "(",
    "0": ")",
    "-": "_",
    "=": "+",
    "[": "{",
    "]": "}",
    "\\": "|",
    ";": ":",
    "'": '"',
    ",": "<",
    ".": ">",
    "/": "?",
    "`": "~",
  };
  return numberShifts[char] || char;
}

// Common Ctrl+key shortcuts
export const CTRL_KEYS = {
  C: withCtrl("c"), // Interrupt
  D: withCtrl("d"), // EOF
  Z: withCtrl("z"), // Suspend
  L: withCtrl("l"), // Clear
  A: withCtrl("a"), // Beginning of line
  E: withCtrl("e"), // End of line
  K: withCtrl("k"), // Kill to end of line
  U: withCtrl("u"), // Kill to beginning of line
  W: withCtrl("w"), // Kill previous word
  R: withCtrl("r"), // Reverse search
  P: withCtrl("p"), // Previous command (like up arrow)
  N: withCtrl("n"), // Next command (like down arrow)
} as const;
