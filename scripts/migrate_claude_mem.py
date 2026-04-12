#!/usr/bin/env python3
"""
MemPalace Autopilot — one-shot bulk import from claude-mem's SQLite database.

Locates the claude-mem SQLite DB, copies it to avoid WAL lock issues, reads
all observations, maps types to MemPalace rooms, scrubs secrets, and mines
each observation into MemPalace.

Usage:
    python3 scripts/migrate_claude_mem.py [--dry-run]
"""

import argparse
import glob
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SEARCH_PATHS = [
    str(Path.home() / ".claude-mem"),
    str(Path.home() / ".claude" / "plugins" / "cache" / "thedotmack" / "claude-mem"),
]

TYPE_TO_ROOM = {
    "bugfix": "problems",
    "feature": "milestones",
    "decision": "decisions",
    "discovery": "technical",
    "change": "milestones",
}

TMP_DB_COPY = "/tmp/claude-mem-migration-copy.sqlite"

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
# Secret scrubbing
# ---------------------------------------------------------------------------


def scrub_secrets(text: str) -> str:
    """Replace any detected secrets in *text* with [REDACTED]."""
    for pattern in SCRUB_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


# ---------------------------------------------------------------------------
# DB location
# ---------------------------------------------------------------------------


def locate_claude_mem_db() -> str | None:
    """
    Search SEARCH_PATHS for a claude-mem SQLite database file.
    Returns the absolute path to the first match, or None if not found.
    """
    extensions = ("*.sqlite", "*.db", "*.sqlite3")
    for base_path in SEARCH_PATHS:
        expanded = os.path.expanduser(base_path)
        if not os.path.isdir(expanded):
            continue
        for ext in extensions:
            # Recursive search
            pattern = os.path.join(expanded, "**", ext)
            matches = glob.glob(pattern, recursive=True)
            if matches:
                return matches[0]
    return None


# ---------------------------------------------------------------------------
# WAL-safe DB copy
# ---------------------------------------------------------------------------


def copy_db_for_reading(source_path: str, dest_path: str = TMP_DB_COPY) -> str:
    """
    Copy the SQLite DB (and associated WAL/SHM sidecar files) to *dest_path*
    to avoid WAL file lock issues when reading.
    Returns *dest_path*.
    """
    shutil.copy2(source_path, dest_path)

    for suffix in ("-wal", "-shm"):
        sidecar = source_path + suffix
        if os.path.exists(sidecar):
            shutil.copy2(sidecar, dest_path + suffix)

    return dest_path


# ---------------------------------------------------------------------------
# Type → room mapping
# ---------------------------------------------------------------------------


def map_type_to_room(obs_type: str) -> str:
    """Return the MemPalace room name for a given claude-mem observation type."""
    return TYPE_TO_ROOM.get((obs_type or "").lower().strip(), "general")


# ---------------------------------------------------------------------------
# Wing determination
# ---------------------------------------------------------------------------


def map_project_to_wing(project: str | None) -> str:
    """Return the MemPalace wing for a given project tag (or 'general' if absent)."""
    if project and project.strip():
        return project.strip()
    return "general"


# ---------------------------------------------------------------------------
# MemPalace mining
# ---------------------------------------------------------------------------


def mine_content(content: str, wing: str, room: str, dry_run: bool = False) -> bool:
    """
    Create a temp directory with mempalace.yaml + content file, then run
    `mempalace mine <dir> --wing=<wing>`.

    mempalace mine requires a directory (not a single file) with a
    mempalace.yaml config inside it. We create this structure on the fly.

    Returns True on success, False on failure.
    Skips the actual subprocess call when *dry_run* is True.
    """
    tmp_dir = None
    try:
        tmp_dir = tempfile.mkdtemp(prefix="mempalace_migrate_")

        # Write mempalace.yaml (required by mempalace mine)
        yaml_path = os.path.join(tmp_dir, "mempalace.yaml")
        with open(yaml_path, "w", encoding="utf-8") as f:
            f.write(f"wing: {wing}\n")

        # Write content file
        content_path = os.path.join(tmp_dir, "observation.md")
        with open(content_path, "w", encoding="utf-8") as f:
            f.write(content)

        if dry_run:
            print(f"  [dry-run] Would mine to wing={wing!r}, room={room!r}: {content[:80]!r}…")
            return True

        result = subprocess.run(
            ["mempalace", "mine", tmp_dir, "--wing", wing],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return result.returncode == 0
    except Exception as exc:
        print(f"  [error] mine_content failed: {exc}", file=sys.stderr)
        return False
    finally:
        if tmp_dir and os.path.exists(tmp_dir):
            try:
                shutil.rmtree(tmp_dir)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Per-observation migration
# ---------------------------------------------------------------------------


def _build_observation_content(row: dict) -> str:
    """Build rich content from claude-mem observation fields.

    claude-mem stores observations with: title, subtitle, narrative, facts, concepts.
    The 'text' field is often None. We combine the meaningful fields.
    """
    parts = []
    title = row.get("title", "")
    subtitle = row.get("subtitle", "")
    narrative = row.get("narrative", "")
    facts = row.get("facts", "")
    text = row.get("text", "")

    if title and str(title) != "None":
        parts.append(f"# {title}")
    if subtitle and str(subtitle) != "None":
        parts.append(subtitle)
    if narrative and str(narrative) != "None":
        parts.append(str(narrative))
    elif text and str(text) != "None":
        parts.append(str(text))
    if facts and str(facts) != "None":
        parts.append(f"Facts: {facts}")

    return "\n\n".join(parts)


def _build_summary_content(row: dict) -> str:
    """Build content from a session_summaries row."""
    parts = []
    request = row.get("request", "")
    learned = row.get("learned", "")
    completed = row.get("completed", "")
    notes = row.get("notes", "")

    if request and str(request) != "None":
        parts.append(f"# {request}")
    if learned and str(learned) != "None":
        parts.append(f"Learned: {learned}")
    if completed and str(completed) != "None":
        parts.append(f"Completed: {completed}")
    if notes and str(notes) != "None":
        parts.append(f"Notes: {notes}")

    return "\n\n".join(parts)


def migrate_observation(
    row: dict,
    dry_run: bool = False,
    is_summary: bool = False,
) -> tuple[bool, str, str]:
    """
    Migrate a single observation or session summary row.

    Returns (success: bool, wing: str, room: str).
    """
    obs_type = row.get("type", "")
    project = row.get("project") or row.get("project_tag") or row.get("tags")

    if is_summary:
        content_raw = _build_summary_content(row)
        room = "milestones"
    else:
        content_raw = _build_observation_content(row)
        room = map_type_to_room(obs_type)

    wing = map_project_to_wing(project)

    # Scrub secrets before sending to MemPalace
    content = scrub_secrets(str(content_raw))

    if not content.strip():
        return False, wing, room

    success = mine_content(content, wing, room, dry_run=dry_run)
    return success, wing, room


# ---------------------------------------------------------------------------
# Main migration logic
# ---------------------------------------------------------------------------


def read_observations_and_summaries(db_path: str) -> tuple[list[dict], list[dict]]:
    """
    Open the SQLite DB at *db_path*, read from the 'observations' and
    'session_summaries' tables specifically (not FTS internal tables).

    Returns (observations, summaries) as lists of dicts.
    """
    observations: list[dict] = []
    summaries: list[dict] = []
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        cur = con.cursor()

        # Read observations
        try:
            cur.execute("SELECT * FROM observations ORDER BY created_at_epoch")
            observations = [dict(row) for row in cur.fetchall()]
        except Exception as exc:
            print(f"  [warn] Could not read observations: {exc}", file=sys.stderr)

        # Read session summaries
        try:
            cur.execute("SELECT * FROM session_summaries ORDER BY created_at_epoch")
            summaries = [dict(row) for row in cur.fetchall()]
        except Exception as exc:
            print(f"  [warn] Could not read session_summaries: {exc}", file=sys.stderr)
    finally:
        con.close()
    return observations, summaries


def run_migration(dry_run: bool = False) -> None:
    """Locate DB, copy it, migrate all observations, print stats, clean up."""
    # --- Locate DB ---
    db_path = locate_claude_mem_db()
    if db_path is None:
        print(
            "ERROR: claude-mem SQLite database not found.\n"
            "Searched paths:\n"
            + "\n".join(f"  - {p}" for p in SEARCH_PATHS)
            + "\n\n"
            "Make sure the claude-mem plugin is installed and has been used at least once.\n"
            "You can also set a custom path by editing SEARCH_PATHS in this script.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Found claude-mem DB: {db_path}")

    # --- WAL-safe copy ---
    copy_path = copy_db_for_reading(db_path, TMP_DB_COPY)
    print(f"Copied DB to: {copy_path}")

    try:
        # --- Read observations + summaries ---
        observations, summaries = read_observations_and_summaries(copy_path)
        print(f"Observations found: {len(observations)}")
        print(f"Session summaries found: {len(summaries)}")
        total = len(observations) + len(summaries)

        if total == 0:
            print("Nothing to migrate.")
            return

        # --- Migrate observations ---
        success_count = 0
        skipped_count = 0
        failed_count = 0
        per_wing: dict[str, int] = {}

        print(f"\nMigrating {len(observations)} observations...")
        for i, row in enumerate(observations, start=1):
            ok, wing, room = migrate_observation(row, dry_run=dry_run)

            if ok:
                success_count += 1
                per_wing[wing] = per_wing.get(wing, 0) + 1
            else:
                content = _build_observation_content(row)
                if not content.strip():
                    skipped_count += 1
                else:
                    failed_count += 1

            if not dry_run and i % 50 == 0:
                print(f"  Observations: {i}/{len(observations)}...")

        # --- Migrate session summaries ---
        print(f"\nMigrating {len(summaries)} session summaries...")
        for i, row in enumerate(summaries, start=1):
            ok, wing, room = migrate_observation(row, dry_run=dry_run, is_summary=True)

            if ok:
                success_count += 1
                per_wing[wing] = per_wing.get(wing, 0) + 1
            else:
                content = _build_summary_content(row)
                if not content.strip():
                    skipped_count += 1
                else:
                    failed_count += 1

            if not dry_run and i % 50 == 0:
                print(f"  Summaries: {i}/{len(summaries)}...")

        # --- Stats ---
        print("\n--- Migration Summary ---")
        print(f"  Total:    {total}")
        print(f"  Success:  {success_count}")
        print(f"  Skipped:  {skipped_count}  (empty content)")
        print(f"  Failed:   {failed_count}")
        print("\n  Per-wing breakdown:")
        if per_wing:
            for wing, count in sorted(per_wing.items()):
                print(f"    {wing}: {count}")
        else:
            print("    (none)")

        if dry_run:
            print("\n[dry-run] No data was actually written to MemPalace.")

    finally:
        # --- Clean up temp copy ---
        for path in (copy_path, copy_path + "-wal", copy_path + "-shm"):
            if os.path.exists(path):
                try:
                    os.unlink(path)
                except OSError:
                    pass
        print("\nCleaned up temporary DB copy.")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bulk-import observations from claude-mem's SQLite DB into MemPalace."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be mined without actually calling MemPalace.",
    )
    args = parser.parse_args()
    run_migration(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
