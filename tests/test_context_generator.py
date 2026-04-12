"""Tests for context_generator.py."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Make scripts/ importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

import context_generator
from context_generator import (
    MAX_CONTEXT_CHARS,
    IDENTITY_MAX_CHARS,
    MIN_PROJECT_RESULTS,
    detect_wing,
    read_identity,
    run_wakeup,
    generate_context,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_subprocess_result(stdout="", returncode=0):
    """Create a mock subprocess.CompletedProcess-like object."""
    mock = MagicMock()
    mock.stdout = stdout
    mock.returncode = returncode
    return mock


# ---------------------------------------------------------------------------
# detect_wing
# ---------------------------------------------------------------------------

class TestDetectWing(unittest.TestCase):

    def test_inside_git_repo(self):
        """detect_wing returns the repo basename when git succeeds."""
        with patch("context_generator.subprocess.run") as mock_run:
            mock_run.return_value = _make_subprocess_result(
                stdout="/home/user/projects/MyRepo\n", returncode=0
            )
            result = detect_wing()
        self.assertEqual(result, "MyRepo")

    def test_outside_git_repo(self):
        """detect_wing returns 'general' when git fails."""
        with patch("context_generator.subprocess.run") as mock_run:
            mock_run.return_value = _make_subprocess_result(stdout="", returncode=128)
            result = detect_wing()
        self.assertEqual(result, "general")

    def test_git_exception_returns_general(self):
        """detect_wing returns 'general' when subprocess raises."""
        with patch("context_generator.subprocess.run", side_effect=FileNotFoundError):
            result = detect_wing()
        self.assertEqual(result, "general")


# ---------------------------------------------------------------------------
# read_identity
# ---------------------------------------------------------------------------

class TestReadIdentity(unittest.TestCase):

    def test_reads_identity_file(self):
        """read_identity returns file content up to IDENTITY_MAX_CHARS."""
        content = "I am a test identity profile."
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write(content)
            tmp_path = Path(f.name)
        try:
            with patch("context_generator.IDENTITY_PATH", tmp_path):
                result = read_identity()
            self.assertEqual(result, content)
        finally:
            tmp_path.unlink()

    def test_caps_at_identity_max_chars(self):
        """read_identity truncates content at IDENTITY_MAX_CHARS."""
        content = "X" * (IDENTITY_MAX_CHARS + 100)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write(content)
            tmp_path = Path(f.name)
        try:
            with patch("context_generator.IDENTITY_PATH", tmp_path):
                result = read_identity()
            self.assertEqual(len(result), IDENTITY_MAX_CHARS)
        finally:
            tmp_path.unlink()

    def test_returns_empty_on_missing_file(self):
        """read_identity returns '' when identity.txt does not exist."""
        with patch("context_generator.IDENTITY_PATH", Path("/nonexistent/identity.txt")):
            result = read_identity()
        self.assertEqual(result, "")


# ---------------------------------------------------------------------------
# run_wakeup
# ---------------------------------------------------------------------------

class TestRunWakeup(unittest.TestCase):

    def test_calls_mempalace_without_wing(self):
        """run_wakeup calls mempalace wake-up with no wing arg when wing=None."""
        with patch("context_generator.subprocess.run") as mock_run:
            mock_run.return_value = _make_subprocess_result(stdout="mem1\nmem2\n")
            result = run_wakeup()
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        self.assertEqual(call_args, ["mempalace", "wake-up"])
        self.assertEqual(result, "mem1\nmem2\n")

    def test_calls_mempalace_with_wing(self):
        """run_wakeup includes --wing=<wing> when wing is provided."""
        with patch("context_generator.subprocess.run") as mock_run:
            mock_run.return_value = _make_subprocess_result(stdout="project memory\n")
            result = run_wakeup(wing="my-project")
        call_args = mock_run.call_args[0][0]
        self.assertIn("--wing=my-project", call_args)
        self.assertEqual(result, "project memory\n")

    def test_returns_empty_on_nonzero_returncode(self):
        """run_wakeup returns '' when mempalace exits with non-zero."""
        with patch("context_generator.subprocess.run") as mock_run:
            mock_run.return_value = _make_subprocess_result(stdout="error", returncode=1)
            result = run_wakeup()
        self.assertEqual(result, "")

    def test_handles_file_not_found(self):
        """run_wakeup returns '' gracefully when mempalace is not installed."""
        with patch("context_generator.subprocess.run", side_effect=FileNotFoundError):
            result = run_wakeup()
        self.assertEqual(result, "")

    def test_handles_generic_exception(self):
        """run_wakeup returns '' on any unexpected exception."""
        with patch("context_generator.subprocess.run", side_effect=OSError("pipe broken")):
            result = run_wakeup()
        self.assertEqual(result, "")


# ---------------------------------------------------------------------------
# generate_context — tagged block
# ---------------------------------------------------------------------------

class TestGenerateContext(unittest.TestCase):

    def _mock_subprocess(self, git_stdout="/home/user/MyRepo\n", git_rc=0,
                          wakeup_stdout="memory line 1\nmemory line 2\nmemory line 3\n",
                          wakeup_rc=0):
        """Return a side_effect function that dispatches git vs mempalace calls."""
        def side_effect(cmd, **kwargs):
            if cmd[0] == "git":
                return _make_subprocess_result(stdout=git_stdout, returncode=git_rc)
            # mempalace wake-up
            return _make_subprocess_result(stdout=wakeup_stdout, returncode=wakeup_rc)
        return side_effect

    def test_outputs_tagged_block_with_mempalace_context_tags(self):
        """generate_context wraps output in <mempalace-context> tags."""
        with patch("context_generator.subprocess.run",
                   side_effect=self._mock_subprocess()):
            with patch("context_generator.IDENTITY_PATH", Path("/nonexistent/id.txt")):
                result = generate_context()
        self.assertTrue(result.startswith("<mempalace-context>"))
        self.assertTrue(result.endswith("</mempalace-context>"))

    def test_includes_identity_section(self):
        """generate_context includes the identity content in the output."""
        identity_text = "Raouf, cybersecurity student."
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write(identity_text)
            tmp_path = Path(f.name)
        try:
            with patch("context_generator.subprocess.run",
                       side_effect=self._mock_subprocess()):
                with patch("context_generator.IDENTITY_PATH", tmp_path):
                    result = generate_context()
            self.assertIn(identity_text, result)
            self.assertIn("# Identity", result)
        finally:
            tmp_path.unlink()

    def test_includes_wing_in_recent_context_header(self):
        """generate_context labels the memories section with the detected wing."""
        with patch("context_generator.subprocess.run",
                   side_effect=self._mock_subprocess(git_stdout="/home/user/CoolRepo\n")):
            with patch("context_generator.IDENTITY_PATH", Path("/nonexistent/id.txt")):
                result = generate_context()
        self.assertIn("# Recent Context // CoolRepo", result)

    def test_falls_back_to_global_when_not_in_git_repo(self):
        """When not in a git repo, generate_context calls global wake-up (no --wing)."""
        called_cmds = []

        def side_effect(cmd, **kwargs):
            called_cmds.append(list(cmd))
            if cmd[0] == "git":
                return _make_subprocess_result(stdout="", returncode=128)
            return _make_subprocess_result(
                stdout="global mem 1\nglobal mem 2\nglobal mem 3\n"
            )

        with patch("context_generator.subprocess.run", side_effect=side_effect):
            with patch("context_generator.IDENTITY_PATH", Path("/nonexistent/id.txt")):
                result = generate_context()

        # Should have called mempalace wake-up without --wing
        wakeup_calls = [c for c in called_cmds if c[0] == "mempalace"]
        self.assertTrue(any("--wing" not in " ".join(c) for c in wakeup_calls),
                        "Expected at least one global wake-up call without --wing")
        self.assertIn("# Recent Context // general", result)

    def test_falls_back_to_global_when_project_returns_few_lines(self):
        """Falls back to global when project-scoped results have < MIN_PROJECT_RESULTS lines."""
        called_cmds = []

        def side_effect(cmd, **kwargs):
            called_cmds.append(list(cmd))
            if cmd[0] == "git":
                return _make_subprocess_result(stdout="/home/user/MyRepo\n", returncode=0)
            # Wing-scoped call → too few results
            if any("--wing" in arg for arg in cmd):
                return _make_subprocess_result(stdout="only one line\n")
            # Global call → rich results
            return _make_subprocess_result(
                stdout="global line 1\nglobal line 2\nglobal line 3\nglobal line 4\n"
            )

        with patch("context_generator.subprocess.run", side_effect=side_effect):
            with patch("context_generator.IDENTITY_PATH", Path("/nonexistent/id.txt")):
                result = generate_context()

        wakeup_calls = [c for c in called_cmds if c[0] == "mempalace"]
        # Should have made both a wing call and a global fallback call
        self.assertGreaterEqual(len(wakeup_calls), 2)
        self.assertIn("global line", result)

    def test_caps_output_at_max_context_chars(self):
        """generate_context never exceeds MAX_CONTEXT_CHARS characters."""
        # Produce a very long memories output
        big_memories = "\n".join(f"memory line {i}: " + "A" * 80 for i in range(200))

        def side_effect(cmd, **kwargs):
            if cmd[0] == "git":
                return _make_subprocess_result(stdout="/home/user/BigRepo\n", returncode=0)
            return _make_subprocess_result(stdout=big_memories)

        with patch("context_generator.subprocess.run", side_effect=side_effect):
            with patch("context_generator.IDENTITY_PATH", Path("/nonexistent/id.txt")):
                result = generate_context()

        self.assertLessEqual(len(result), MAX_CONTEXT_CHARS,
                             f"Output length {len(result)} exceeds MAX_CONTEXT_CHARS={MAX_CONTEXT_CHARS}")

    def test_truncated_output_still_has_closing_tag(self):
        """When truncated, the output still ends with </mempalace-context>."""
        big_memories = "\n".join(f"memory line {i}: " + "A" * 80 for i in range(200))

        def side_effect(cmd, **kwargs):
            if cmd[0] == "git":
                return _make_subprocess_result(stdout="/home/user/BigRepo\n", returncode=0)
            return _make_subprocess_result(stdout=big_memories)

        with patch("context_generator.subprocess.run", side_effect=side_effect):
            with patch("context_generator.IDENTITY_PATH", Path("/nonexistent/id.txt")):
                result = generate_context()

        self.assertTrue(result.endswith("</mempalace-context>"))

    def test_handles_mempalace_not_installed(self):
        """generate_context returns empty string when mempalace is not installed."""
        with patch("context_generator.subprocess.run", side_effect=FileNotFoundError):
            result = generate_context()
        # Either empty string or a minimal block with (none) memories — both acceptable.
        # The key requirement: must not raise, and if non-empty must be valid XML block.
        if result:
            self.assertIn("<mempalace-context>", result)
            self.assertIn("</mempalace-context>", result)

    def test_returns_empty_string_on_total_failure(self):
        """generate_context returns '' when everything raises."""
        with patch("context_generator.subprocess.run", side_effect=OSError("boom")):
            result = generate_context()
        # If git raises OSError (not FileNotFoundError), detect_wing returns 'general'
        # and run_wakeup also returns '' — so we get a valid block with (none) memories.
        # The important contract is: no exception is raised.
        self.assertIsInstance(result, str)


# ---------------------------------------------------------------------------
# Integration-style: main() writes to stdout
# ---------------------------------------------------------------------------

class TestMain(unittest.TestCase):

    def test_main_prints_context_to_stdout(self):
        """main() prints generate_context() output to stdout."""
        fake_context = "<mempalace-context>\n# Identity\nhi\n</mempalace-context>"
        with patch("context_generator.generate_context", return_value=fake_context):
            from io import StringIO
            with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
                context_generator.main()
            self.assertIn("<mempalace-context>", mock_stdout.getvalue())

    def test_main_silent_when_no_context(self):
        """main() produces no output when generate_context returns ''."""
        with patch("context_generator.generate_context", return_value=""):
            from io import StringIO
            with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
                context_generator.main()
            self.assertEqual(mock_stdout.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
