"""Shared constants used across the application."""

# =============================================================================
# Model Constants - SINGLE SOURCE OF TRUTH
# =============================================================================
# Update these when new model versions are released.
# All code should import from here, not hardcode model strings.

# Claude models (Anthropic)
CLAUDE_SONNET = "claude-sonnet-4-5"
CLAUDE_OPUS = "claude-opus-4-6"
CLAUDE_HAIKU = "claude-haiku-4-5"

# Full model IDs (for APIs that need them)
CLAUDE_OPUS_FULL = "claude-opus-4-6-20260201"
CLAUDE_SONNET_FULL = "claude-sonnet-4-5-20251101"

# Gemini 3 models (Google)
GEMINI_FLASH = "gemini-3-flash-preview"
GEMINI_PRO = "gemini-3-pro-preview"

# Gemini image generation model
GEMINI_IMAGE = "gemini-3-pro-image-preview"

# Agent Hub agents (use agent:slug format)
# These route to Agent Hub which provides mandate injection, model fallback, etc.
AGENT_WORKER = "agent:coder"  # Code generation worker (Flash-based with Sonnet fallback)
AGENT_SUPERVISOR = "agent:supervisor"  # Supervisor for coordination (Sonnet-based)
AGENT_REVIEWER = "agent:reviewer"  # Code review (Opus-based)
AGENT_DEBUGGER = "agent:debugger"  # Bug fixing with root cause analysis
AGENT_TRIAGER = "agent:triager"  # Task triage and clarity assessment (Flash-based)

# Default models for each use case
DEFAULT_CLAUDE_MODEL = CLAUDE_SONNET
DEFAULT_GEMINI_MODEL = GEMINI_FLASH

# Model for complex reasoning (code review, architecture decisions)
REASONING_CLAUDE_MODEL = CLAUDE_OPUS
REASONING_GEMINI_MODEL = GEMINI_PRO

# Model for fast/cheap operations (extraction, validation)
FAST_CLAUDE_MODEL = CLAUDE_HAIKU
FAST_GEMINI_MODEL = GEMINI_FLASH


# =============================================================================
# QA Review Thresholds
# =============================================================================
# These control when the QA review loop escalates to different agents/modes

# Number of worker retry attempts before escalating to supervisor
QA_WORKER_STUCK_THRESHOLD = 3

# Number of supervisor attempts before full escalation
QA_SUPERVISOR_STUCK_THRESHOLD = 2

# =============================================================================
# Self-Healing Retry Constants
# =============================================================================
# When step verification fails, agent gets a chance to self-correct before escalating

# Number of pristine self-heal attempts before blocking task execution
PRISTINE_SELF_HEAL_MAX_ATTEMPTS = 3

# Number of self-fix attempts before requesting supervisor guidance
SELF_HEAL_MAX_ATTEMPTS = 3

# Number of supervisor-guided fix attempts before full escalation
SUPERVISOR_GUIDED_MAX_ATTEMPTS = 3

# Model to escalate to during supervisor-guided retry phase
ESCALATION_MODEL = CLAUDE_OPUS

# Context window usage threshold (%) for starting a fresh session
CONTEXT_FRESHNESS_THRESHOLD = 80

# Total number of QA review attempts before full escalation
QA_ESCALATION_THRESHOLD = 5

# Maximum number of QA review iterations before giving up
QA_MAX_ITERATIONS = 50
