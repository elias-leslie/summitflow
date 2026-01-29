"""Constants for AI review task."""

# Confidence threshold for filtering AI review issues (80% = 0.80)
# Issues from reviews below this threshold are logged but not counted as failures
CONFIDENCE_THRESHOLD = 0.80

# High-risk file patterns that require human review
# These patterns match sensitive areas: auth, database, API schemas, credentials
HIGH_RISK_FILE_PATTERNS = [
    # Authentication and authorization
    r"auth[/\._-]",
    r"login",
    r"session",
    r"oauth",
    r"jwt",
    r"permission",
    # Credentials and secrets
    r"password",
    r"credential",
    r"secret",
    r"token",
    r"api[_-]?key",
    r"\.env",
    # Database and migrations
    r"migration",
    r"schema\.py",
    r"models\.py",
    r"\.sql$",
    r"alembic",
    # API schemas and contracts
    r"openapi",
    r"swagger",
    r"schemas/",
    r"api/.*schema",
    # Security-sensitive directories
    r"/security/",
    r"/crypto/",
    r"/payment/",
]

# Medium-risk patterns (flagged but not auto-escalated)
MEDIUM_RISK_FILE_PATTERNS = [
    r"config",
    r"settings",
    r"middleware",
    r"celery",
    r"redis",
]

# API contract patterns that may indicate breaking changes
API_CONTRACT_PATTERNS = [
    # Python function signatures
    r"^-\s*def\s+\w+\s*\(",  # Removed function definition
    r"^-\s*class\s+\w+",  # Removed class
    r"^-\s*@(api|router|app)\.",  # Removed API decorator
    # TypeScript/JavaScript exports
    r"^-\s*export\s+(const|function|class|interface|type)",  # Removed export
    r"^-\s*export\s+default",  # Removed default export
    # Props and types
    r"^-\s*interface\s+\w+Props",  # Removed Props interface
    r"^-\s*type\s+\w+Props",  # Removed Props type
    # API schemas
    r"^-\s*(class|def)\s+\w+(Schema|Request|Response)",  # Removed schema
]

SECURITY_KEYWORDS = [
    "security",
    "injection",
    "xss",
    "csrf",
    "authentication",
    "authorization",
    "credential",
    "password",
    "secret",
    "token",
    "vulnerability",
    "exploit",
    "data exposure",
    "sql injection",
]

ARCHITECTURE_KEYWORDS = [
    "breaking change",
    "architectural",
    "fundamental",
    "refactor required",
    "wrong approach",
]
