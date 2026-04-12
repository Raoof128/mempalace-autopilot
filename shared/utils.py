"""
MemPalace Autopilot — shared utilities.

Provides SCRUB_PATTERNS, scrub_secrets(), and detect_wing() so that
hooks/hook_runner.py, scripts/context_generator.py, and
scripts/migrate_claude_mem.py all use a single canonical implementation.
"""

import re
import subprocess
from pathlib import Path

# ---------------------------------------------------------------------------
# Secret scrubbing
# ---------------------------------------------------------------------------

SCRUB_PATTERNS: list[re.Pattern] = [
    # AWS access key IDs
    re.compile(r"AKIA[0-9A-Z]{16}", re.ASCII),
    # OpenAI / Stripe secret keys (sk-... up to ~60 chars)
    re.compile(r"sk-[A-Za-z0-9]{20,60}", re.ASCII),
    # GitHub tokens
    re.compile(r"ghp_[A-Za-z0-9]{36}", re.ASCII),
    re.compile(r"gho_[A-Za-z0-9]{36}", re.ASCII),
    re.compile(r"github_pat_[A-Za-z0-9_]{59}", re.ASCII),
    # Bearer tokens in headers / env vars
    re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]{20,}", re.IGNORECASE),
    # Slack tokens
    re.compile(r"xoxb-[0-9A-Za-z\-]{40,}", re.ASCII),
    re.compile(r"xoxp-[0-9A-Za-z\-]{40,}", re.ASCII),
    re.compile(r"xoxs-[0-9A-Za-z\-]{40,}", re.ASCII),
    # Generic key=value / key: value patterns (e.g. api_key=..., secret=...)
    re.compile(
        r'(?i)(?:api[-_]?key|secret|token|password|passwd|pwd)\s*[=:]\s*["\']?[A-Za-z0-9\-._~+/]{8,}["\']?',
        re.ASCII,
    ),
]


def scrub_secrets(text: str) -> str:
    """Replace any detected secrets in *text* with [REDACTED]."""
    for pattern in SCRUB_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


# ---------------------------------------------------------------------------
# Wing detection
# ---------------------------------------------------------------------------


def detect_wing() -> str:
    """Return the git repository name as the wing, or 'general' if not in a repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return Path(result.stdout.strip()).name
    except Exception:
        pass
    return "general"
