"""Tests for hook_runner shared utilities."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Make hooks/ importable
sys.path.insert(0, str(Path(__file__).parent.parent / "hooks"))

from hook_runner import (
    SAVE_INTERVAL,
    detect_wing,
    scrub_secrets,
    count_human_messages,
    extract_transcript_delta,
    get_state_file,
    read_last_save_index,
    write_last_save_index,
    get_transcript_line_count,
)


# ---------------------------------------------------------------------------
# detect_wing
# ---------------------------------------------------------------------------

class TestDetectWing(unittest.TestCase):

    def test_inside_git_repo(self):
        """When git succeeds, detect_wing returns the repo directory basename."""
        with patch("hook_runner.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "/home/user/projects/MyRepo\n"
            result = detect_wing()
        self.assertEqual(result, "MyRepo")

    def test_outside_git_repo(self):
        """When git fails, detect_wing returns 'general'."""
        with patch("hook_runner.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 128
            mock_run.return_value.stdout = ""
            result = detect_wing()
        self.assertEqual(result, "general")

    def test_git_exception_returns_general(self):
        """When subprocess raises, detect_wing returns 'general'."""
        with patch("hook_runner.subprocess.run", side_effect=FileNotFoundError):
            result = detect_wing()
        self.assertEqual(result, "general")


# ---------------------------------------------------------------------------
# scrub_secrets
# ---------------------------------------------------------------------------

class TestScrubSecrets(unittest.TestCase):

    def test_aws_key(self):
        text = "My key is AKIAIOSFODNN7EXAMPLE"
        result = scrub_secrets(text)
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", result)
        self.assertIn("[REDACTED]", result)

    def test_openai_key(self):
        text = "token = sk-abcdefghijklmnopqrstuvwxyz123456789012"
        result = scrub_secrets(text)
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz123456789012", result)
        self.assertIn("[REDACTED]", result)

    def test_github_ghp_token(self):
        text = "export TOKEN=ghp_" + "A" * 36
        result = scrub_secrets(text)
        self.assertNotIn("ghp_" + "A" * 36, result)
        self.assertIn("[REDACTED]", result)

    def test_github_gho_token(self):
        text = "auth=gho_" + "B" * 36
        result = scrub_secrets(text)
        self.assertNotIn("gho_" + "B" * 36, result)
        self.assertIn("[REDACTED]", result)

    def test_github_pat_token(self):
        text = "pat=github_pat_" + "C" * 59
        result = scrub_secrets(text)
        self.assertNotIn("github_pat_" + "C" * 59, result)
        self.assertIn("[REDACTED]", result)

    def test_bearer_token(self):
        text = "Authorization: Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9xyzABCD"
        result = scrub_secrets(text)
        self.assertIn("[REDACTED]", result)

    def test_slack_xoxb_token(self):
        text = "SLACK_TOKEN=xoxb-" + "1" * 40
        result = scrub_secrets(text)
        self.assertNotIn("xoxb-" + "1" * 40, result)
        self.assertIn("[REDACTED]", result)

    def test_slack_xoxp_token(self):
        text = "tok=xoxp-" + "2" * 40
        result = scrub_secrets(text)
        self.assertNotIn("xoxp-" + "2" * 40, result)
        self.assertIn("[REDACTED]", result)

    def test_slack_xoxs_token(self):
        text = "tok=xoxs-" + "3" * 40
        result = scrub_secrets(text)
        self.assertNotIn("xoxs-" + "3" * 40, result)
        self.assertIn("[REDACTED]", result)

    def test_generic_key_value(self):
        text = "api_key=supersecretvalue123"
        result = scrub_secrets(text)
        self.assertIn("[REDACTED]", result)

    def test_normal_text_preserved(self):
        text = "Hello, this is a normal sentence without any secrets."
        result = scrub_secrets(text)
        self.assertEqual(result, text)

    def test_multiple_secrets_scrubbed(self):
        key1 = "AKIAIOSFODNN7EXAMPLE"
        key2 = "sk-" + "z" * 30
        text = f"key1={key1} and key2={key2}"
        result = scrub_secrets(text)
        self.assertNotIn(key1, result)
        self.assertNotIn(key2, result)


# ---------------------------------------------------------------------------
# count_human_messages
# ---------------------------------------------------------------------------

class TestCountHumanMessages(unittest.TestCase):

    def _write_jsonl(self, entries):
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
        )
        for entry in entries:
            tmp.write(json.dumps(entry) + "\n")
        tmp.close()
        return tmp.name

    def test_counts_user_messages_only(self):
        entries = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
            {"role": "user", "content": "How are you?"},
            {"role": "system", "content": "You are helpful"},
        ]
        path = self._write_jsonl(entries)
        try:
            self.assertEqual(count_human_messages(path), 2)
        finally:
            os.unlink(path)

    def test_excludes_command_messages(self):
        entries = [
            {"role": "user", "content": "Hello"},
            {"role": "user", "content": "<command-message>run tests</command-message>"},
            {"role": "user", "content": "Normal message"},
        ]
        path = self._write_jsonl(entries)
        try:
            self.assertEqual(count_human_messages(path), 2)
        finally:
            os.unlink(path)

    def test_empty_file_returns_zero(self):
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
        )
        tmp.close()
        try:
            self.assertEqual(count_human_messages(tmp.name), 0)
        finally:
            os.unlink(tmp.name)

    def test_nonexistent_file_returns_zero(self):
        self.assertEqual(count_human_messages("/nonexistent/path/file.jsonl"), 0)

    def test_command_message_in_list_content(self):
        entries = [
            {"role": "user", "content": [{"type": "text", "text": "<command-message>cmd</command-message>"}]},
            {"role": "user", "content": "Real message"},
        ]
        path = self._write_jsonl(entries)
        try:
            self.assertEqual(count_human_messages(path), 1)
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# extract_transcript_delta
# ---------------------------------------------------------------------------

class TestExtractTranscriptDelta(unittest.TestCase):

    def _write_jsonl(self, entries):
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
        )
        for entry in entries:
            tmp.write(json.dumps(entry) + "\n")
        tmp.close()
        return tmp.name

    def test_basic_delta_extraction(self):
        entries = [
            {"role": "user", "content": "msg0"},
            {"role": "assistant", "content": "reply0"},
            {"role": "user", "content": "msg1"},
            {"role": "assistant", "content": "reply1"},
        ]
        path = self._write_jsonl(entries)
        try:
            # last_index=2 → only last two entries
            result = extract_transcript_delta(path, last_index=2)
            self.assertIn("msg1", result)
            self.assertIn("reply1", result)
            self.assertNotIn("msg0", result)
        finally:
            os.unlink(path)

    def test_filters_system_messages(self):
        entries = [
            {"role": "system", "content": "You are an assistant"},
            {"role": "user", "content": "Hello"},
        ]
        path = self._write_jsonl(entries)
        try:
            result = extract_transcript_delta(path)
            self.assertNotIn("You are an assistant", result)
            self.assertIn("Hello", result)
        finally:
            os.unlink(path)

    def test_filters_command_messages(self):
        entries = [
            {"role": "user", "content": "<command-message>do thing</command-message>"},
            {"role": "user", "content": "Real question"},
        ]
        path = self._write_jsonl(entries)
        try:
            result = extract_transcript_delta(path)
            self.assertNotIn("do thing", result)
            self.assertIn("Real question", result)
        finally:
            os.unlink(path)

    def test_tool_result_truncation(self):
        long_content = "X" * 600
        entries = [
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "content": long_content}
                ],
            }
        ]
        path = self._write_jsonl(entries)
        try:
            result = extract_transcript_delta(path)
            self.assertIn("[truncated]", result)
            # Original long content should be cut down
            self.assertNotIn("X" * 600, result)
        finally:
            os.unlink(path)

    def test_secret_scrubbing_in_output(self):
        secret = "AKIAIOSFODNN7EXAMPLE"
        entries = [
            {"role": "user", "content": f"My key is {secret}"},
        ]
        path = self._write_jsonl(entries)
        try:
            result = extract_transcript_delta(path)
            self.assertNotIn(secret, result)
            self.assertIn("[REDACTED]", result)
        finally:
            os.unlink(path)

    def test_empty_file(self):
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
        )
        tmp.close()
        try:
            result = extract_transcript_delta(tmp.name)
            self.assertEqual(result, "")
        finally:
            os.unlink(tmp.name)

    def test_full_transcript_when_last_index_zero(self):
        entries = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "second"},
        ]
        path = self._write_jsonl(entries)
        try:
            result = extract_transcript_delta(path, last_index=0)
            self.assertIn("first", result)
            self.assertIn("second", result)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
