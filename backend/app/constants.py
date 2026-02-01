"""Shared constants used across the application."""

# =============================================================================
# Model Constants - SINGLE SOURCE OF TRUTH
# =============================================================================
# Update these when new model versions are released.
# All code should import from here, not hardcode model strings.

# Claude 4.5 models (Anthropic)
CLAUDE_SONNET = "claude-sonnet-4-5"
CLAUDE_OPUS = "claude-opus-4-5"
CLAUDE_HAIKU = "claude-haiku-4-5"

# Full model IDs (for APIs that need them)
CLAUDE_OPUS_FULL = "claude-opus-4-5-20251101"
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
AGENT_FIXER = "agent:fixer"  # Error fixing (Sonnet-based with escalation)
AGENT_QA = "agent:qa"  # QA supervisor for task quality review (Opus-based)
AGENT_IDEA_INTAKE = "agent:idea-intake"  # Idea triage and clarification (Flash-based)

# Default models for each use case
DEFAULT_CLAUDE_MODEL = CLAUDE_SONNET
DEFAULT_GEMINI_MODEL = GEMINI_FLASH

# Model for complex reasoning (code review, architecture decisions)
REASONING_CLAUDE_MODEL = CLAUDE_OPUS
REASONING_GEMINI_MODEL = GEMINI_PRO

# Model for fast/cheap operations (extraction, validation)
FAST_CLAUDE_MODEL = CLAUDE_HAIKU
FAST_GEMINI_MODEL = GEMINI_FLASH

# Valid model lists for validation
VALID_CLAUDE_MODELS = (
    CLAUDE_SONNET,
    CLAUDE_OPUS,
    CLAUDE_HAIKU,
    # Shorthand aliases
    "sonnet",
    "opus",
    "haiku",
)

VALID_GEMINI_MODELS = (
    GEMINI_FLASH,
    GEMINI_PRO,
)

VALID_AGENT_MODELS = (
    AGENT_WORKER,
    AGENT_SUPERVISOR,
    AGENT_REVIEWER,
    AGENT_FIXER,
    AGENT_QA,
    AGENT_IDEA_INTAKE,
)

# =============================================================================
# QA Review Thresholds
# =============================================================================
# These control when the QA review loop escalates to different agents/modes

# Number of worker retry attempts before escalating to supervisor
QA_WORKER_STUCK_THRESHOLD = 3

# Number of supervisor attempts before escalating to human
QA_SUPERVISOR_STUCK_THRESHOLD = 2

# =============================================================================
# Self-Healing Retry Constants
# =============================================================================
# When step verification fails, agent gets a chance to self-correct before escalating

# Number of self-fix attempts before requesting supervisor guidance
SELF_HEAL_MAX_ATTEMPTS = 2

# Number of supervisor-guided fix attempts before escalating to human
SUPERVISOR_GUIDED_MAX_ATTEMPTS = 2

# Total number of QA review attempts before escalation to human
QA_ESCALATION_THRESHOLD = 5

# Maximum number of QA review iterations before giving up
QA_MAX_ITERATIONS = 50
