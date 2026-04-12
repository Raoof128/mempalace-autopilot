#!/usr/bin/env python3
"""
MemPalace Autopilot — single entry point for all Claude Code lifecycle hooks.
Dispatches to handler functions based on the event name passed as argv[1].
"""

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SAVE_INTERVAL = 15
STATE_DIR = Path.home() / ".mempalace" / "hook_state"
MAX_TOOL_RESULT_LEN = 500

SCRUB_PATTERNS = [
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


# ---------------------------------------------------------------------------
# Shared utilities
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


def scrub_secrets(text: str) -> str:
    """Replace any detected secrets in *text* with [REDACTED]."""
    for pattern in SCRUB_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def count_human_messages(transcript_path: str) -> int:
    """
    Count lines where role=='user' in the JSONL transcript,
    excluding lines that contain a <command-message> tag.
    """
    count = 0
    try:
        with open(transcript_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("role") != "user":
                    continue
                # Skip synthetic command messages injected by the harness
                content = entry.get("content", "")
                if isinstance(content, list):
                    # content can be a list of blocks
                    text = " ".join(
                        b.get("text", "") if isinstance(b, dict) else str(b)
                        for b in content
                    )
                else:
                    text = str(content)
                if "<command-message>" in text:
                    continue
                count += 1
    except (OSError, IOError):
        pass
    return count


def extract_transcript_delta(transcript_path: str, last_index: int = 0) -> str:
    """
    Read JSONL entries from *last_index* onwards.
    Filters out system messages and command messages.
    Truncates tool results longer than MAX_TOOL_RESULT_LEN chars.
    Applies secret scrubbing to the output.
    Returns a formatted text representation of the conversation delta.
    """
    lines_out: list[str] = []
    try:
        with open(transcript_path, "r", encoding="utf-8") as fh:
            all_lines = fh.readlines()

        for line in all_lines[last_index:]:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            role = entry.get("role", "")

            # Drop system messages entirely
            if role == "system":
                continue

            content = entry.get("content", "")

            # Normalise content to a plain string
            if isinstance(content, list):
                parts: list[str] = []
                for block in content:
                    if not isinstance(block, dict):
                        parts.append(str(block))
                        continue
                    block_type = block.get("type", "")
                    if block_type == "tool_result":
                        result_text = block.get("content", "")
                        if isinstance(result_text, list):
                            result_text = " ".join(
                                b.get("text", "") if isinstance(b, dict) else str(b)
                                for b in result_text
                            )
                        result_text = str(result_text)
                        if len(result_text) > MAX_TOOL_RESULT_LEN:
                            result_text = result_text[:MAX_TOOL_RESULT_LEN] + "…[truncated]"
                        parts.append(f"[tool_result] {result_text}")
                    elif block_type == "tool_use":
                        parts.append(
                            f"[tool_use:{block.get('name', '')}] {json.dumps(block.get('input', {}))}"
                        )
                    else:
                        parts.append(block.get("text", str(block)))
                text = "\n".join(parts)
            else:
                text = str(content)

            # Skip harness command messages
            if "<command-message>" in text:
                continue

            lines_out.append(f"{role}: {text}")

    except (OSError, IOError):
        pass

    combined = "\n\n".join(lines_out)
    return scrub_secrets(combined)


def get_state_file(session_id: str) -> Path:
    """Return the path to the state file for *session_id*."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return STATE_DIR / f"{session_id}.json"


def read_last_save_index(session_id: str) -> int:
    """Return the last saved transcript line index for this session (0 if unknown)."""
    state_file = get_state_file(session_id)
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
        return int(data.get("last_index", 0))
    except Exception:
        return 0


def write_last_save_index(session_id: str, index: int) -> None:
    """Persist *index* as the last saved transcript line index for *session_id*."""
    state_file = get_state_file(session_id)
    state_file.write_text(json.dumps({"last_index": index}), encoding="utf-8")


def mine_temp_file(content: str, wing: str) -> bool:
    """
    Create a temp directory with mempalace.yaml + content file, then run
    `mempalace mine <dir> --wing <wing>`.

    mempalace mine requires a directory with a mempalace.yaml config.
    Cleans up the temp directory in all cases.
    Returns True on success, False on failure.
    """
    tmp_dir = None
    try:
        tmp_dir = tempfile.mkdtemp(prefix="mempalace_capture_")

        # Write mempalace.yaml (required by mempalace mine)
        with open(os.path.join(tmp_dir, "mempalace.yaml"), "w", encoding="utf-8") as f:
            f.write(f"wing: {wing}\n")

        # Write content file
        with open(os.path.join(tmp_dir, "transcript.md"), "w", encoding="utf-8") as f:
            f.write(content)

        result = subprocess.run(
            ["mempalace", "mine", tmp_dir, "--wing", wing],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return result.returncode == 0
    except Exception:
        return False
    finally:
        if tmp_dir and os.path.exists(tmp_dir):
            import shutil
            try:
                shutil.rmtree(tmp_dir)
            except OSError:
                pass


def get_transcript_line_count(transcript_path: str) -> int:
    """Return the number of non-empty lines in the JSONL transcript."""
    try:
        with open(transcript_path, "r", encoding="utf-8") as fh:
            return sum(1 for line in fh if line.strip())
    except (OSError, IOError):
        return 0


# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------


def handle_session_start(stdin_data: str) -> None:
    """
    SessionStart: call context_generator.py and print its output.
    Silent on failure — must never block the session from starting.
    """
    try:
        script_dir = Path(__file__).parent.parent / "scripts"
        context_script = script_dir / "context_generator.py"
        result = subprocess.run(
            ["python3", str(context_script)],
            input=stdin_data,
            capture_output=True,
            text=True,
            timeout=25,
        )
        if result.stdout:
            print(result.stdout, end="")
    except Exception:
        pass


def handle_stop(stdin_data: str) -> None:
    """
    Stop hook: periodically capture conversation delta into MemPalace.
    Interval-gated; guards against re-entrancy via stop_hook_active.
    """
    try:
        data = json.loads(stdin_data) if stdin_data.strip() else {}
    except json.JSONDecodeError:
        data = {}

    # Infinite-loop guard
    if data.get("stop_hook_active"):
        print("{}")
        return

    session_id = data.get("session_id", "unknown")
    transcript_path = data.get("transcript_path", "")

    human_count = count_human_messages(transcript_path)
    last_index = read_last_save_index(session_id)

    # Only save every SAVE_INTERVAL human messages since last save
    # We track total human messages; diff against a stored baseline would be
    # cleaner, but the spec says "check against SAVE_INTERVAL since last save",
    # so we store the count at last save in the state file.
    try:
        state_file = get_state_file(session_id)
        state_data = json.loads(state_file.read_text(encoding="utf-8"))
        last_human_count = int(state_data.get("last_human_count", 0))
    except Exception:
        last_human_count = 0

    if human_count - last_human_count < SAVE_INTERVAL:
        print("{}")
        return

    # Capture delta
    delta = extract_transcript_delta(transcript_path, last_index)
    if delta.strip():
        wing = detect_wing()
        mine_temp_file(delta, wing)

    # Update state
    new_index = get_transcript_line_count(transcript_path)
    state_file = get_state_file(session_id)
    state_file.write_text(
        json.dumps({"last_index": new_index, "last_human_count": human_count}),
        encoding="utf-8",
    )

    print("{}")


def handle_precompact(stdin_data: str) -> None:
    """
    PreCompact hook: always extract and mine the delta, then block to allow
    MemPalace to finish before the context is compressed.
    """
    try:
        data = json.loads(stdin_data) if stdin_data.strip() else {}
    except json.JSONDecodeError:
        data = {}

    session_id = data.get("session_id", "unknown")
    transcript_path = data.get("transcript_path", "")

    last_index = read_last_save_index(session_id)
    delta = extract_transcript_delta(transcript_path, last_index)

    if delta.strip():
        wing = detect_wing()
        mine_temp_file(delta, wing)

    new_index = get_transcript_line_count(transcript_path)
    write_last_save_index(session_id, new_index)

    print(json.dumps({
        "decision": "block",
        "reason": "MEMPALACE: saving context before compaction...",
    }))


def handle_session_end(stdin_data: str) -> None:
    """
    SessionEnd: extract only the final delta since last save, mine it,
    clean up the state file, then exit cleanly.
    """
    try:
        data = json.loads(stdin_data) if stdin_data.strip() else {}
    except json.JSONDecodeError:
        data = {}

    session_id = data.get("session_id", "unknown")
    transcript_path = data.get("transcript_path", "")

    last_index = read_last_save_index(session_id)
    delta = extract_transcript_delta(transcript_path, last_index)

    if delta.strip():
        wing = detect_wing()
        mine_temp_file(delta, wing)

    # Clean up state file for this session
    state_file = get_state_file(session_id)
    try:
        state_file.unlink()
    except OSError:
        pass

    print("{}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: hook_runner.py <event>", file=sys.stderr)
        sys.exit(1)

    event = sys.argv[1].lower()

    # Read stdin only when it's not a TTY (i.e. when data is actually piped in)
    if not sys.stdin.isatty():
        stdin_data = sys.stdin.read()
    else:
        stdin_data = "{}"

    dispatch = {
        "session-start": handle_session_start,
        "stop": handle_stop,
        "precompact": handle_precompact,
        "session-end": handle_session_end,
    }

    handler = dispatch.get(event)
    if handler is None:
        print(f"hook_runner: unknown event '{event}'", file=sys.stderr)
        sys.exit(1)

    handler(stdin_data)


if __name__ == "__main__":
    main()
