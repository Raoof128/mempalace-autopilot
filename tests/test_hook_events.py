"""Tests for hook_runner event handlers."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Make hooks/ importable
sys.path.insert(0, str(Path(__file__).parent.parent / "hooks"))

import hook_runner
from hook_runner import (
    handle_stop,
    handle_precompact,
    handle_session_end,
    handle_session_start,
    SAVE_INTERVAL,
    STATE_DIR,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_transcript(entries):
    """Write a list of dicts as JSONL to a temp file; return its path."""
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
    )
    for entry in entries:
        tmp.write(json.dumps(entry) + "\n")
    tmp.close()
    return tmp.name


def _make_user_messages(n):
    return [{"role": "user", "content": f"msg{i}"} for i in range(n)]


# ---------------------------------------------------------------------------
# handle_stop
# ---------------------------------------------------------------------------

class TestHandleStop(unittest.TestCase):

    def test_exits_immediately_when_stop_hook_active(self):
        """stop_hook_active=True causes {} to be printed and returns early."""
        data = json.dumps({"session_id": "abc", "transcript_path": "", "stop_hook_active": True})
        with patch("builtins.print") as mock_print:
            handle_stop(data)
        mock_print.assert_called_once_with("{}")

    def test_skips_mine_when_below_interval(self):
        """When human message count is below SAVE_INTERVAL, skip mining."""
        entries = _make_user_messages(SAVE_INTERVAL - 1)
        path = _write_transcript(entries)
        try:
            data = json.dumps({"session_id": "test-skip", "transcript_path": path, "stop_hook_active": False})
            with patch("hook_runner.mine_temp_file") as mock_mine:
                with patch("builtins.print") as mock_print:
                    handle_stop(data)
                mock_mine.assert_not_called()
                mock_print.assert_called_once_with("{}")
        finally:
            os.unlink(path)

    def test_mines_when_interval_reached(self):
        """When human messages >= SAVE_INTERVAL, mining is triggered."""
        entries = _make_user_messages(SAVE_INTERVAL)
        path = _write_transcript(entries)
        session_id = "test-mine-interval"
        # Remove any stale state file
        state_file = STATE_DIR / f"{session_id}.json"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        if state_file.exists():
            state_file.unlink()
        try:
            data = json.dumps({
                "session_id": session_id,
                "transcript_path": path,
                "stop_hook_active": False,
            })
            with patch("hook_runner.mine_temp_file", return_value=True) as mock_mine:
                with patch("hook_runner.detect_wing", return_value="test-wing"):
                    with patch("builtins.print") as mock_print:
                        handle_stop(data)
                mock_mine.assert_called_once()
                # Wing arg
                _, kwargs_or_args = mock_mine.call_args[0], mock_mine.call_args
                self.assertEqual(mock_mine.call_args[0][1], "test-wing")
                mock_print.assert_called_once_with("{}")
        finally:
            os.unlink(path)
            if state_file.exists():
                state_file.unlink()

    def test_stop_prints_empty_json(self):
        """handle_stop always prints {} at the end."""
        entries = _make_user_messages(2)
        path = _write_transcript(entries)
        try:
            data = json.dumps({"session_id": "test-empty", "transcript_path": path, "stop_hook_active": False})
            with patch("hook_runner.mine_temp_file"):
                with patch("builtins.print") as mock_print:
                    handle_stop(data)
            mock_print.assert_called_with("{}")
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# handle_precompact
# ---------------------------------------------------------------------------

class TestHandlePrecompact(unittest.TestCase):

    def test_precompact_always_mines(self):
        """precompact mines even when human message count is below SAVE_INTERVAL."""
        entries = [{"role": "user", "content": "hello"}]
        path = _write_transcript(entries)
        session_id = "test-precompact"
        state_file = STATE_DIR / f"{session_id}.json"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        if state_file.exists():
            state_file.unlink()
        try:
            data = json.dumps({"session_id": session_id, "transcript_path": path})
            with patch("hook_runner.mine_temp_file", return_value=True) as mock_mine:
                with patch("hook_runner.detect_wing", return_value="repo-wing"):
                    with patch("builtins.print"):
                        handle_precompact(data)
            mock_mine.assert_called_once()
        finally:
            os.unlink(path)
            if state_file.exists():
                state_file.unlink()

    def test_precompact_blocks(self):
        """precompact always returns a block decision."""
        entries = [{"role": "user", "content": "compact me"}]
        path = _write_transcript(entries)
        session_id = "test-precompact-block"
        state_file = STATE_DIR / f"{session_id}.json"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        if state_file.exists():
            state_file.unlink()
        try:
            data = json.dumps({"session_id": session_id, "transcript_path": path})
            printed = []
            with patch("hook_runner.mine_temp_file", return_value=True):
                with patch("hook_runner.detect_wing", return_value="wing"):
                    with patch("builtins.print", side_effect=lambda x: printed.append(x)):
                        handle_precompact(data)
            self.assertEqual(len(printed), 1)
            response = json.loads(printed[0])
            self.assertEqual(response["decision"], "block")
            self.assertIn("MEMPALACE", response["reason"])
        finally:
            os.unlink(path)
            if state_file.exists():
                state_file.unlink()

    def test_precompact_updates_state(self):
        """precompact updates the state file with the new line count."""
        entries = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "world"},
        ]
        path = _write_transcript(entries)
        session_id = "test-precompact-state"
        state_file = STATE_DIR / f"{session_id}.json"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        if state_file.exists():
            state_file.unlink()
        try:
            data = json.dumps({"session_id": session_id, "transcript_path": path})
            with patch("hook_runner.mine_temp_file", return_value=True):
                with patch("hook_runner.detect_wing", return_value="wing"):
                    with patch("builtins.print"):
                        handle_precompact(data)
            saved = json.loads(state_file.read_text())
            self.assertEqual(saved["last_index"], 2)
        finally:
            os.unlink(path)
            if state_file.exists():
                state_file.unlink()


# ---------------------------------------------------------------------------
# handle_session_end
# ---------------------------------------------------------------------------

class TestHandleSessionEnd(unittest.TestCase):

    def test_session_end_mines_final_delta(self):
        """session-end mines only the delta since last save."""
        entries = [
            {"role": "user", "content": "old message"},
            {"role": "user", "content": "new final message"},
        ]
        path = _write_transcript(entries)
        session_id = "test-session-end"
        state_file = STATE_DIR / f"{session_id}.json"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        # Set last_index to 1 so only the second message is in the delta
        state_file.write_text(json.dumps({"last_index": 1}))
        try:
            data = json.dumps({"session_id": session_id, "transcript_path": path})
            mined_content = []
            def fake_mine(content, wing):
                mined_content.append(content)
                return True
            with patch("hook_runner.mine_temp_file", side_effect=fake_mine):
                with patch("hook_runner.detect_wing", return_value="wing"):
                    with patch("builtins.print"):
                        handle_session_end(data)
            self.assertEqual(len(mined_content), 1)
            self.assertIn("new final message", mined_content[0])
            self.assertNotIn("old message", mined_content[0])
        finally:
            os.unlink(path)
            if state_file.exists():
                state_file.unlink()

    def test_session_end_cleans_state(self):
        """session-end deletes the state file after saving."""
        entries = [{"role": "user", "content": "last words"}]
        path = _write_transcript(entries)
        session_id = "test-cleanup"
        state_file = STATE_DIR / f"{session_id}.json"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(json.dumps({"last_index": 0}))
        try:
            data = json.dumps({"session_id": session_id, "transcript_path": path})
            with patch("hook_runner.mine_temp_file", return_value=True):
                with patch("hook_runner.detect_wing", return_value="wing"):
                    with patch("builtins.print"):
                        handle_session_end(data)
            self.assertFalse(state_file.exists(), "State file should be deleted after session-end")
        finally:
            os.unlink(path)
            if state_file.exists():
                state_file.unlink()

    def test_session_end_prints_empty_json(self):
        """session-end prints {}."""
        entries = [{"role": "user", "content": "bye"}]
        path = _write_transcript(entries)
        session_id = "test-session-end-print"
        state_file = STATE_DIR / f"{session_id}.json"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        if state_file.exists():
            state_file.unlink()
        try:
            data = json.dumps({"session_id": session_id, "transcript_path": path})
            with patch("hook_runner.mine_temp_file", return_value=True):
                with patch("hook_runner.detect_wing", return_value="wing"):
                    with patch("builtins.print") as mock_print:
                        handle_session_end(data)
            mock_print.assert_called_once_with("{}")
        finally:
            os.unlink(path)
            if state_file.exists():
                state_file.unlink()


# ---------------------------------------------------------------------------
# handle_session_start
# ---------------------------------------------------------------------------

class TestHandleSessionStart(unittest.TestCase):

    def test_session_start_outputs_context(self):
        """session-start prints whatever context_generator outputs."""
        mock_result = MagicMock()
        mock_result.stdout = "Relevant context from MemPalace\n"
        mock_result.returncode = 0
        with patch("hook_runner.subprocess.run", return_value=mock_result) as mock_run:
            with patch("builtins.print") as mock_print:
                handle_session_start("{}")
        mock_run.assert_called_once()
        mock_print.assert_called_once_with("Relevant context from MemPalace\n", end="")

    def test_session_start_silent_on_failure(self):
        """session-start does not raise or print on subprocess failure."""
        with patch("hook_runner.subprocess.run", side_effect=FileNotFoundError):
            # Should not raise
            try:
                handle_session_start("{}")
            except Exception as exc:
                self.fail(f"handle_session_start raised {exc}")

    def test_session_start_silent_when_no_output(self):
        """session-start is silent when context_generator produces no output."""
        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.returncode = 0
        with patch("hook_runner.subprocess.run", return_value=mock_result):
            with patch("builtins.print") as mock_print:
                handle_session_start("{}")
        mock_print.assert_not_called()


if __name__ == "__main__":
    unittest.main()
