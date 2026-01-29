/**
 * Model constants - single source of truth for model IDs.
 * Keep in sync with backend/app/constants.py
 */

// Claude 4.5 models (Anthropic)
export const CLAUDE_SONNET = 'claude-sonnet-4-5'
export const CLAUDE_OPUS = 'claude-opus-4-5'
export const CLAUDE_HAIKU = 'claude-haiku-4-5'

// Gemini 3 models (Google)
export const GEMINI_FLASH = 'gemini-3-flash-preview'
export const GEMINI_PRO = 'gemini-3-pro-preview'

// Default models
export const DEFAULT_CLAUDE_MODEL = CLAUDE_SONNET
export const DEFAULT_GEMINI_MODEL = GEMINI_FLASH

// Model display names
export const MODEL_DISPLAY_NAMES: Record<string, string> = {
  [CLAUDE_OPUS]: 'Claude Opus 4.5',
  [CLAUDE_SONNET]: 'Claude Sonnet 4.5',
  [CLAUDE_HAIKU]: 'Claude Haiku 4.5',
  [GEMINI_PRO]: 'Gemini 3 Pro',
  [GEMINI_FLASH]: 'Gemini 3 Flash',
}

// Model options for dropdowns
export const CLAUDE_MODEL_OPTIONS = [
  {
    id: 'default',
    label: `Default (${MODEL_DISPLAY_NAMES[DEFAULT_CLAUDE_MODEL]})`,
  },
  { id: CLAUDE_OPUS, label: MODEL_DISPLAY_NAMES[CLAUDE_OPUS] },
  { id: CLAUDE_SONNET, label: MODEL_DISPLAY_NAMES[CLAUDE_SONNET] },
  { id: CLAUDE_HAIKU, label: MODEL_DISPLAY_NAMES[CLAUDE_HAIKU] },
]

export const GEMINI_MODEL_OPTIONS = [
  {
    id: 'default',
    label: `Default (${MODEL_DISPLAY_NAMES[DEFAULT_GEMINI_MODEL]})`,
  },
  { id: GEMINI_PRO, label: MODEL_DISPLAY_NAMES[GEMINI_PRO] },
  { id: GEMINI_FLASH, label: MODEL_DISPLAY_NAMES[GEMINI_FLASH] },
]
