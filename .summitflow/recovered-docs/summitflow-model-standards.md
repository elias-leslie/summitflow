# Model Standards - MANDATORY

Use centralized constants for all AI model references. Never hardcode model strings.

## Source of Truth

All model constants are defined in `backend/app/constants.py`:

```python
# Claude 4.5 models
CLAUDE_SONNET = "claude-sonnet-4-5"  # Default for most tasks
CLAUDE_OPUS = "claude-opus-4-5"      # Complex reasoning, code review
CLAUDE_HAIKU = "claude-haiku-4-5"    # Fast/cheap operations

# Gemini 3 models
GEMINI_FLASH = "gemini-3-flash-preview"  # Default for Gemini
GEMINI_PRO = "gemini-3-pro-preview"      # Better reasoning

# Defaults
DEFAULT_CLAUDE_MODEL = CLAUDE_SONNET
DEFAULT_GEMINI_MODEL = GEMINI_FLASH
```

## Usage

```python
# CORRECT - import from constants
from app.constants import DEFAULT_GEMINI_MODEL, CLAUDE_OPUS
client = GeminiClient(model=DEFAULT_GEMINI_MODEL)

# WRONG - hardcoded string
client = GeminiClient(model="gemini-3-flash-preview")  # NO!
```

## Forbidden

- `gemini-2.5-*` - Legacy, do not use
- `gemini-2.0-*` - Legacy, do not use
- `claude-3-*` - Legacy, do not use
- Any hardcoded model string in code

## When to Update

When new model versions are released:
1. Update `backend/app/constants.py`
2. Update this rule file
3. That's it - all code automatically uses new models
