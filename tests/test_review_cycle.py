from __future__ import annotations

import argparse
import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "review_cycle.py"
SPEC = importlib.util.spec_from_file_location("review_cycle", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
review_cycle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(review_cycle)


def args(state_file: Path, **values: str) -> argparse.Namespace:
    return argparse.Namespace(state_file=str(state_file), **values)


class ReviewCycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.state_file = Path(self.tempdir.name) / "issue.state.json"
        review_cycle.cmd_init(
            args(
                self.state_file,
                issue="#42",
                branch="codex/issue-42",
                manager_id="manager-1",
            )
        )

    def load(self) -> dict:
        return json.loads(self.state_file.read_text(encoding="utf-8"))

    def test_aborted_review_does_not_consume_a_round(self) -> None:
        review_cycle.cmd_start_review(args(self.state_file))
        review_cycle.cmd_abort_review(args(self.state_file, reason="reviewer unavailable"))

        state = self.load()
        self.assertEqual(state["review_count"], 0)
        self.assertFalse(state["active_review"])
        self.assertEqual(state["history"][-1]["kind"], "review_aborted")

    def test_fifteenth_round_fix_closes_local_review_without_round_sixteen(self) -> None:
        for round_number in range(1, review_cycle.MAX_REVIEWS + 1):
            review_cycle.cmd_start_review(args(self.state_file))
            review_cycle.cmd_finish_review(
                args(
                    self.state_file,
                    outcome="changes",
                    report=f"review-{round_number}.md",
                    summary="one valid finding",
                )
            )
            review_cycle.cmd_record_fix(
                args(
                    self.state_file,
                    report=f"fix-{round_number}.md",
                    validation="tests passed",
                )
            )

        state = self.load()
        self.assertEqual(state["review_count"], review_cycle.MAX_REVIEWS)
        self.assertTrue(state["local_review_closed"])
        self.assertTrue(state["final_unreviewed_fix"])
        with self.assertRaisesRegex(SystemExit, "local review is already closed"):
            review_cycle.cmd_start_review(args(self.state_file))

    def test_full_clean_lifecycle_and_single_feedback_window(self) -> None:
        fixed = datetime(2026, 1, 1, tzinfo=timezone.utc)
        review_cycle.cmd_start_review(args(self.state_file))
        review_cycle.cmd_finish_review(
            args(
                self.state_file,
                outcome="pass",
                report="review-1.md",
                summary="no findings",
            )
        )
        review_cycle.cmd_record_pr(
            args(
                self.state_file,
                url="https://github.com/example/repo/pull/7",
                head_sha="abc123",
                closing_reference="Closes #42",
            )
        )

        with patch.object(review_cycle, "current_time", return_value=fixed):
            review_cycle.cmd_mark_ready(args(self.state_file))
            with self.assertRaisesRegex(SystemExit, "seconds remaining"):
                review_cycle.cmd_mark_feedback_fetched(
                    args(self.state_file, snapshot="feedback.json")
                )

        after_window = fixed + timedelta(seconds=review_cycle.REMOTE_WAIT_SECONDS)
        with patch.object(review_cycle, "current_time", return_value=after_window):
            review_cycle.cmd_mark_feedback_fetched(
                args(self.state_file, snapshot="feedback.json")
            )
        with self.assertRaisesRegex(SystemExit, "already fetched"):
            review_cycle.cmd_mark_feedback_fetched(
                args(self.state_file, snapshot="feedback-again.json")
            )

        review_cycle.cmd_record_remote_assessment(
            args(self.state_file, outcome="clean", report="remote-review.md")
        )
        review_cycle.cmd_record_checks(
            args(
                self.state_file,
                head_sha="abc123",
                result="pass",
                evidence="required checks passed",
            )
        )
        review_cycle.cmd_mark_merged(
            args(self.state_file, merge_sha="def456", evidence="PR merged")
        )
        review_cycle.cmd_verify_issue_closed(
            args(self.state_file, evidence="Issue state is CLOSED")
        )
        review_cycle.cmd_record_remote_branch(
            args(self.state_file, evidence="remote branch absent")
        )
        review_cycle.cmd_record_worktree(
            args(self.state_file, evidence="worktree absent")
        )
        review_cycle.cmd_record_local_branch(
            args(self.state_file, evidence="local branch absent")
        )
        review_cycle.cmd_mark_cleaned(
            args(self.state_file, base_branch_evidence="default branch contains def456")
        )

        state = self.load()
        self.assertEqual(state["stage"], "cleaned")
        self.assertEqual(state["cleanup"]["base_branch"]["evidence"], "default branch contains def456")


class SkillMetadataTests(unittest.TestCase):
    def test_skill_name_and_invocation_are_consistent(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        metadata = (ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
        prompt = (ROOT / "references" / "issue-manager-prompt.md").read_text(encoding="utf-8")

        self.assertIn("name: issue-to-merge", skill)
        self.assertIn("$issue-to-merge", metadata)
        self.assertIn("$issue-to-merge", prompt)
        self.assertNotIn("managed-pr-development", skill + metadata + prompt)


if __name__ == "__main__":
    unittest.main()
