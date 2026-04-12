#!/usr/bin/env python3
"""
MemPalace Autopilot — context generator.
Called by hook_runner.py at session start.
Outputs ~800 tokens of memory context to stdout.
"""

import subprocess
import sys
from pathlib import Path

# Ensure repo root is on sys.path so `shared` package is importable regardless
# of how this script is invoked (directly, via subprocess, or from tests).
_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_CONTEXT_CHARS = 3200
IDENTITY_MAX_CHARS = 400
IDENTITY_PATH = Path.home() / ".mempalace" / "identity.txt"
MIN_PROJECT_RESULTS = 3


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


# ---------------------------------------------------------------------------
# Identity reader
# ---------------------------------------------------------------------------


def read_identity() -> str:
    """Read identity.txt, capped at IDENTITY_MAX_CHARS. Returns '' on failure."""
    try:
        text = IDENTITY_PATH.read_text(encoding="utf-8")
        return text[:IDENTITY_MAX_CHARS]
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# MemPalace wake-up calls
# ---------------------------------------------------------------------------


def run_wakeup(wing: str | None = None) -> str:
    """
    Run `mempalace wake-up [--wing=<wing>]` and return stdout.
    Returns '' on any failure (including mempalace not installed).
    """
    cmd = ["mempalace", "wake-up"]
    if wing:
        cmd.append(f"--wing={wing}")
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=20,
        )
        if result.returncode == 0:
            return result.stdout
        return ""
    except FileNotFoundError:
        return ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Context assembly
# ---------------------------------------------------------------------------


def generate_context() -> str:
    """
    Assemble and return the full mempalace-context block.
    Returns '' on complete failure.
    """
    try:
        wing = detect_wing()
        identity = read_identity()

        # Step 1: try project-scoped memories when in a named wing
        memories = ""
        if wing != "general":
            memories = run_wakeup(wing=wing)

        # Step 2: fall back to global Layer 0+1 when not in a project or too few results
        project_line_count = len([l for l in memories.splitlines() if l.strip()])
        if wing == "general" or project_line_count < MIN_PROJECT_RESULTS:
            global_memories = run_wakeup()
            # Prefer whichever is longer (more content)
            if global_memories:
                memories = global_memories

        # Step 3: format tagged block
        identity_section = f"# Identity\n{identity}" if identity else "# Identity\n(none)"
        memories_section = f"# Recent Context // {wing}\n{memories.strip()}" if memories.strip() else f"# Recent Context // {wing}\n(none)"

        block = f"<mempalace-context>\n{identity_section}\n\n{memories_section}\n</mempalace-context>"

        # Step 4: hard cap at MAX_CONTEXT_CHARS, truncating from bottom
        if len(block) > MAX_CONTEXT_CHARS:
            # Truncate: we want the opening tag, identity, and as much of the
            # memories as fit, then close the tag.
            closing_tag = "\n</mempalace-context>"
            budget = MAX_CONTEXT_CHARS - len(closing_tag)
            block = block[:budget] + closing_tag

        return block

    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    context = generate_context()
    if context:
        print(context)


if __name__ == "__main__":
    main()
