"""Terminal service configuration."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load environment from ~/.env.local
env_file = Path.home() / ".env.local"
if env_file.exists():
    load_dotenv(env_file)

# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL", "")

# Terminal service port
TERMINAL_PORT = int(os.getenv("TERMINAL_PORT", "8002"))

# CORS origins
CORS_ORIGINS = [
    "http://localhost:3001",
    "http://localhost:3002",  # Standalone terminal frontend (local)
    "https://dev.summitflow.dev",
    "https://terminal.summitflow.dev",  # Standalone terminal frontend (production)
]
