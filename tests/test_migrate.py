"""Tests for migrate_claude_mem.py — type mapping, DB location, secret scrubbing,
and observation migration with mocked MemPalace calls."""

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Make scripts/ importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from migrate_claude_mem import (
    map_type_to_room,
    map_project_to_wing,
    scrub_secrets,
    locate_claude_mem_db,
    migrate_observation,
    mine_content,
    SEARCH_PATHS,
    TYPE_TO_ROOM,
)


# ---------------------------------------------------------------------------
# Type mapping
# ---------------------------------------------------------------------------


class TestMapTypeToRoom(unittest.TestCase):
    """All 5 known types plus the unknown/default case."""

    def test_bugfix_maps_to_problems(self):
        self.assertEqual(map_type_to_room("bugfix"), "problems")

    def test_feature_maps_to_milestones(self):
        self.assertEqual(map_type_to_room("feature"), "milestones")

    def test_decision_maps_to_decisions(self):
        self.assertEqual(map_type_to_room("decision"), "decisions")

    def test_discovery_maps_to_technical(self):
        self.assertEqual(map_type_to_room("discovery"), "technical")

    def test_change_maps_to_milestones(self):
        self.assertEqual(map_type_to_room("change"), "milestones")

    def test_unknown_type_maps_to_general(self):
        self.assertEqual(map_type_to_room("unknown_type"), "general")

    def test_empty_string_maps_to_general(self):
        self.assertEqual(map_type_to_room(""), "general")

    def test_none_maps_to_general(self):
        self.assertEqual(map_type_to_room(None), "general")

    def test_type_case_insensitive(self):
        self.assertEqual(map_type_to_room("BUGFIX"), "problems")
        self.assertEqual(map_type_to_room("Feature"), "milestones")


# ---------------------------------------------------------------------------
# Wing determination
# ---------------------------------------------------------------------------


class TestMapProjectToWing(unittest.TestCase):

    def test_project_name_becomes_wing(self):
        self.assertEqual(map_project_to_wing("my-project"), "my-project")

    def test_none_project_becomes_general(self):
        self.assertEqual(map_project_to_wing(None), "general")

    def test_empty_string_becomes_general(self):
        self.assertEqual(map_project_to_wing(""), "general")

    def test_whitespace_only_becomes_general(self):
        self.assertEqual(map_project_to_wing("   "), "general")

    def test_project_name_stripped(self):
        self.assertEqual(map_project_to_wing("  my-repo  "), "my-repo")


# ---------------------------------------------------------------------------
# locate_claude_mem_db
# ---------------------------------------------------------------------------


class TestLocateClaudeMemDb(unittest.TestCase):

    def test_finds_db_in_standard_path(self):
        """locate_claude_mem_db returns a path when a .sqlite file exists in a search path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_file = os.path.join(tmpdir, "memories.sqlite")
            # Create a minimal valid SQLite file
            con = sqlite3.connect(db_file)
            con.close()

            with patch("migrate_claude_mem.SEARCH_PATHS", [tmpdir]):
                result = locate_claude_mem_db()

        self.assertIsNotNone(result)
        self.assertTrue(result.endswith(".sqlite"))

    def test_finds_db_in_nested_subdirectory(self):
        """locate_claude_mem_db recurses into subdirectories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            subdir = os.path.join(tmpdir, "data", "v2")
            os.makedirs(subdir)
            db_file = os.path.join(subdir, "store.db")
            con = sqlite3.connect(db_file)
            con.close()

            with patch("migrate_claude_mem.SEARCH_PATHS", [tmpdir]):
                result = locate_claude_mem_db()

        self.assertIsNotNone(result)
        self.assertTrue(result.endswith(".db"))

    def test_returns_none_when_not_found(self):
        """locate_claude_mem_db returns None when no DB file exists in any search path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # tmpdir exists but contains no .sqlite/.db/.sqlite3 files
            with patch("migrate_claude_mem.SEARCH_PATHS", [tmpdir]):
                result = locate_claude_mem_db()
        self.assertIsNone(result)

    def test_returns_none_when_search_paths_dont_exist(self):
        """locate_claude_mem_db returns None when search dirs do not exist at all."""
        with patch("migrate_claude_mem.SEARCH_PATHS", ["/nonexistent/path/abc123"]):
            result = locate_claude_mem_db()
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# scrub_secrets
# ---------------------------------------------------------------------------


class TestScrubSecrets(unittest.TestCase):

    def test_aws_key_redacted(self):
        text = "My key is AKIAIOSFODNN7EXAMPLE"
        result = scrub_secrets(text)
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", result)
        self.assertIn("[REDACTED]", result)

    def test_openai_key_redacted(self):
        text = "token = sk-abcdefghijklmnopqrstuvwxyz123456789012"
        result = scrub_secrets(text)
        self.assertIn("[REDACTED]", result)

    def test_github_ghp_token_redacted(self):
        text = "export TOKEN=ghp_" + "A" * 36
        result = scrub_secrets(text)
        self.assertIn("[REDACTED]", result)

    def test_bearer_token_redacted(self):
        text = "Authorization: Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9xyzABCD"
        result = scrub_secrets(text)
        self.assertIn("[REDACTED]", result)

    def test_slack_xoxb_token_redacted(self):
        text = "SLACK_TOKEN=xoxb-" + "1" * 40
        result = scrub_secrets(text)
        self.assertIn("[REDACTED]", result)

    def test_generic_api_key_redacted(self):
        text = "api_key=supersecretvalue123"
        result = scrub_secrets(text)
        self.assertIn("[REDACTED]", result)

    def test_normal_text_preserved(self):
        text = "Hello, this is a normal sentence without any secrets."
        result = scrub_secrets(text)
        self.assertEqual(result, text)


# ---------------------------------------------------------------------------
# migrate_observation — calls mine with correct wing (mock mine_content)
# ---------------------------------------------------------------------------


class TestMigrateObservation(unittest.TestCase):
    """Tests use claude-mem's actual field names: title, narrative, facts."""

    def test_uses_correct_room_for_type(self):
        """migrate_observation maps the type to the right room."""
        with patch("migrate_claude_mem.mine_content", return_value=True) as mock_mine:
            ok, wing, room = migrate_observation(
                {"type": "bugfix", "project": "proj", "title": "Fixed a bug", "narrative": "The auth was broken"}
            )
        self.assertTrue(ok)
        self.assertEqual(room, "problems")
        mock_mine.assert_called_once()
        _, call_wing, call_room = mock_mine.call_args[0]
        self.assertEqual(call_wing, "proj")
        self.assertEqual(call_room, "problems")

    def test_uses_project_as_wing(self):
        """migrate_observation uses the project name as wing."""
        with patch("migrate_claude_mem.mine_content", return_value=True) as mock_mine:
            ok, wing, room = migrate_observation(
                {"type": "feature", "project": "my-repo", "title": "Added feature", "narrative": "New login page"}
            )
        self.assertEqual(wing, "my-repo")
        _, call_wing, _ = mock_mine.call_args[0]
        self.assertEqual(call_wing, "my-repo")

    def test_uses_general_wing_when_no_project(self):
        """migrate_observation defaults wing to 'general' when project is absent."""
        with patch("migrate_claude_mem.mine_content", return_value=True) as mock_mine:
            ok, wing, room = migrate_observation(
                {"type": "decision", "narrative": "made a call"}
            )
        self.assertEqual(wing, "general")
        _, call_wing, _ = mock_mine.call_args[0]
        self.assertEqual(call_wing, "general")

    def test_uses_general_wing_when_project_is_none(self):
        """migrate_observation defaults wing to 'general' when project is None."""
        with patch("migrate_claude_mem.mine_content", return_value=True) as mock_mine:
            ok, wing, room = migrate_observation(
                {"type": "discovery", "project": None, "narrative": "found something"}
            )
        self.assertEqual(wing, "general")

    def test_skips_empty_content(self):
        """migrate_observation returns False when all content fields are empty."""
        with patch("migrate_claude_mem.mine_content", return_value=True) as mock_mine:
            ok, wing, room = migrate_observation(
                {"type": "feature", "project": "proj", "title": "None", "narrative": "None", "text": "None"}
            )
        self.assertFalse(ok)
        mock_mine.assert_not_called()

    def test_scrubs_secrets_before_mining(self):
        """migrate_observation scrubs secrets from narrative before calling mine_content."""
        secret = "AKIAIOSFODNN7EXAMPLE"
        with patch("migrate_claude_mem.mine_content", return_value=True) as mock_mine:
            migrate_observation(
                {"type": "change", "project": "proj", "narrative": f"key={secret}"}
            )
        call_content = mock_mine.call_args[0][0]
        self.assertNotIn(secret, call_content)
        self.assertIn("[REDACTED]", call_content)

    def test_dry_run_does_not_call_subprocess(self):
        """In dry-run mode, mine_content must not invoke any subprocess."""
        with patch("migrate_claude_mem.subprocess.run") as mock_run:
            ok, wing, room = migrate_observation(
                {"type": "feature", "project": "proj", "narrative": "some content"},
                dry_run=True,
            )
        mock_run.assert_not_called()
        self.assertTrue(ok)

    def test_builds_content_from_title_and_narrative(self):
        """Content should combine title + narrative."""
        with patch("migrate_claude_mem.mine_content", return_value=True) as mock_mine:
            migrate_observation(
                {"type": "feature", "project": "proj", "title": "Big Feature", "narrative": "Details here"}
            )
        call_content = mock_mine.call_args[0][0]
        self.assertIn("Big Feature", call_content)
        self.assertIn("Details here", call_content)

    def test_fallback_content_fields(self):
        """Falls back to text field when narrative is None."""
        with patch("migrate_claude_mem.mine_content", return_value=True) as mock_mine:
            migrate_observation(
                {"type": "discovery", "project": "proj", "title": "Found it", "text": "via text field", "narrative": "None"}
            )
        call_content = mock_mine.call_args[0][0]
        self.assertIn("via text field", call_content)

    def test_project_tag_field_used_as_wing(self):
        """Falls back to project_tag field for wing."""
        with patch("migrate_claude_mem.mine_content", return_value=True) as mock_mine:
            ok, wing, room = migrate_observation(
                {"type": "feature", "project_tag": "alt-proj", "narrative": "stuff"}
            )
        self.assertEqual(wing, "alt-proj")

    def test_unknown_type_defaults_to_general_room(self):
        """migrate_observation uses 'general' room for unrecognised types."""
        with patch("migrate_claude_mem.mine_content", return_value=True):
            ok, wing, room = migrate_observation(
                {"type": "totally_new_type", "project": "p", "content": "something"}
            )
        self.assertEqual(room, "general")

    def test_old_project_tag_field_used_as_wing(self):
        """migrate_observation recognises 'project_tag' as an alternative project field."""
        with patch("migrate_claude_mem.mine_content", return_value=True) as mock_mine:
            ok, wing, room = migrate_observation(
                {"type": "feature", "project_tag": "alt-project", "narrative": "stuff"}
            )
        self.assertEqual(wing, "alt-project")


# ---------------------------------------------------------------------------
# mine_content
# ---------------------------------------------------------------------------


class TestMineContent(unittest.TestCase):

    def test_dry_run_returns_true_without_subprocess(self):
        with patch("migrate_claude_mem.subprocess.run") as mock_run:
            result = mine_content("some content", "my-wing", "general", dry_run=True)
        self.assertTrue(result)
        mock_run.assert_not_called()

    def test_calls_mempalace_mine_with_wing_flag(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch("migrate_claude_mem.subprocess.run", return_value=mock_result) as mock_run:
            result = mine_content("content here", "the-wing", "problems", dry_run=False)
        self.assertTrue(result)
        cmd = mock_run.call_args[0][0]
        self.assertEqual(cmd[0], "mempalace")
        self.assertEqual(cmd[1], "mine")
        self.assertIn("--wing=the-wing", cmd)

    def test_returns_false_on_subprocess_failure(self):
        mock_result = MagicMock()
        mock_result.returncode = 1
        with patch("migrate_claude_mem.subprocess.run", return_value=mock_result):
            result = mine_content("content here", "wing", "room", dry_run=False)
        self.assertFalse(result)

    def test_returns_false_on_exception(self):
        with patch("migrate_claude_mem.subprocess.run", side_effect=FileNotFoundError):
            result = mine_content("content", "wing", "room", dry_run=False)
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
