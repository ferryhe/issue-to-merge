from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
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
                branch="agent/issue-42",
                manager_id="manager-1",
            )
        )

    def load(self) -> dict:
        return json.loads(self.state_file.read_text(encoding="utf-8"))

    def record_worker_and_start_implementation(
        self,
        *,
        worker_id: str = "worker-1",
        worker_profile: str = "hermes-worker",
        worker_provider: str = "anthropic",
        worker_model: str = "claude-sonnet",
    ) -> None:
        review_cycle.cmd_record_worker(
            args(
                self.state_file,
                worker_id=worker_id,
                worker_profile=worker_profile,
                worker_provider=worker_provider,
                worker_model=worker_model,
                continuity="worker_identity_profile",
            )
        )
        review_cycle.cmd_start_implementation(
            args(
                self.state_file,
                worker_id=worker_id,
                worker_profile=worker_profile,
                worker_provider=worker_provider,
                worker_model=worker_model,
            )
        )

    def test_init_starts_in_worker_selection_stage(self) -> None:
        state = self.load()
        self.assertEqual(state["stage"], "worker_selection")
        self.assertIsNone(state["implementation_started_at"])
        self.assertFalse(state["legacy_in_progress"])

    def test_aborted_review_does_not_consume_a_round(self) -> None:
        self.record_worker_and_start_implementation()
        review_cycle.cmd_start_review(
            args(
                self.state_file,
                reviewer_id="reviewer-1",
                reviewer_profile="hermes-reviewer",
            )
        )
        review_cycle.cmd_abort_review(args(self.state_file, reason="reviewer unavailable"))

        state = self.load()
        self.assertEqual(state["review_count"], 0)
        self.assertFalse(state["active_review"])
        self.assertEqual(state["history"][-1]["kind"], "review_aborted")
        self.assertEqual(state["history"][-1]["reviewer_id"], "reviewer-1")
        self.assertEqual(state["history"][-1]["reviewer_profile"], "hermes-reviewer")

    def test_fifteenth_round_fix_closes_local_review_without_round_sixteen(self) -> None:
        self.record_worker_and_start_implementation()
        for round_number in range(1, review_cycle.MAX_REVIEWS + 1):
            review_cycle.cmd_start_review(
                args(
                    self.state_file,
                    reviewer_id=f"reviewer-{round_number}",
                    reviewer_profile="hermes-reviewer",
                )
            )
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
                    worker_id="worker-1",
                    worker_profile="hermes-worker",
                    worker_provider="anthropic",
                    worker_model="claude-sonnet",
                    report=f"fix-{round_number}.md",
                    validation="tests passed",
                )
            )

        state = self.load()
        self.assertEqual(state["review_count"], review_cycle.MAX_REVIEWS)
        self.assertTrue(state["local_review_closed"])
        self.assertTrue(state["final_unreviewed_fix"])
        with self.assertRaisesRegex(SystemExit, "local review is already closed"):
            review_cycle.cmd_start_review(
                args(
                    self.state_file,
                    reviewer_id="reviewer-16",
                    reviewer_profile="hermes-reviewer",
                )
            )

    def test_full_clean_lifecycle_and_single_feedback_window(self) -> None:
        fixed = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.record_worker_and_start_implementation(
            worker_provider="openai",
            worker_model="gpt-5-codex",
        )
        review_cycle.cmd_start_review(
            args(
                self.state_file,
                reviewer_id="reviewer-1",
                reviewer_profile="hermes-reviewer",
            )
        )
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
            args(
                self.state_file,
                outcome="clean",
                report="remote-review.md",
                worker_id="worker-1",
                worker_profile="hermes-worker",
                worker_provider="openai",
                worker_model="gpt-5-codex",
            )
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
        with self.assertRaisesRegex(SystemExit, "complete cleanup before recording task closure"):
            review_cycle.cmd_mark_task_closed(
                args(self.state_file, evidence="Issue task closed")
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
        review_cycle.cmd_mark_task_closed(
            args(self.state_file, evidence="Issue task closed and resources released")
        )
        with self.assertRaisesRegex(SystemExit, "Issue task closure is already recorded"):
            review_cycle.cmd_mark_task_closed(
                args(self.state_file, evidence="duplicate closure proof")
            )

        state = self.load()
        self.assertEqual(state["stage"], "task_closed")
        self.assertEqual(state["cleanup"]["base_branch"]["evidence"], "default branch contains def456")
        self.assertEqual(
            state["task_close"]["evidence"],
            "Issue task closed and resources released",
        )

    def test_schema_v3_state_without_new_fields_is_still_readable(self) -> None:
        state = self.load()
        for key in (
            "worker",
            "worker_continuity",
            "active_reviewer",
            "used_reviewer_ids",
            "check_repair_count",
            "check_repairs",
            "implementation_started_at",
            "legacy_in_progress",
        ):
            state.pop(key, None)
        state["stage"] = "implementing"
        self.state_file.write_text(json.dumps(state), encoding="utf-8")

        loaded = review_cycle.cmd_status(args(self.state_file))

        self.assertIsNone(loaded["worker"])
        self.assertEqual(loaded["worker_continuity"], "worker_identity_profile")
        self.assertIsNone(loaded["active_reviewer"])
        self.assertEqual(loaded["used_reviewer_ids"], [])
        self.assertEqual(loaded["check_repair_count"], 0)
        self.assertEqual(loaded["check_repairs"], [])
        self.assertIsNone(loaded["implementation_started_at"])
        self.assertFalse(loaded["legacy_in_progress"])

    def test_late_first_worker_record_is_rejected_after_worker_selection_stage(self) -> None:
        state = self.load()
        state["stage"] = "implementing"
        self.state_file.write_text(json.dumps(state), encoding="utf-8")

        with self.assertRaisesRegex(SystemExit, "first-time worker recording is allowed only in worker_selection"):
            review_cycle.cmd_record_worker(
                args(
                    self.state_file,
                    worker_id="worker-1",
                    worker_profile="issue-worker",
                    worker_provider="openai",
                    worker_model="gpt-5",
                    continuity="worker_identity_profile",
                )
            )

    def test_start_implementation_requires_recorded_worker_and_exact_route(self) -> None:
        with self.assertRaisesRegex(SystemExit, "record the implementation worker before starting implementation"):
            review_cycle.cmd_start_implementation(
                args(
                    self.state_file,
                    worker_id="worker-1",
                    worker_profile="issue-worker",
                    worker_provider="openai",
                    worker_model="gpt-5",
                )
            )

        review_cycle.cmd_record_worker(
            args(
                self.state_file,
                worker_id="worker-1",
                worker_profile="issue-worker",
                worker_provider="openai",
                worker_model="gpt-5",
                continuity="worker_identity_profile",
            )
        )
        with self.assertRaisesRegex(SystemExit, "worker provider/model does not match"):
            review_cycle.cmd_start_implementation(
                args(
                    self.state_file,
                    worker_id="worker-1",
                    worker_profile="issue-worker",
                    worker_provider="anthropic",
                    worker_model="gpt-5",
                )
            )
        review_cycle.cmd_start_implementation(
            args(
                self.state_file,
                worker_id="worker-1",
                worker_profile="issue-worker",
                worker_provider="openai",
                worker_model="gpt-5",
            )
        )

    def test_start_implementation_records_auditable_timestamp_and_order(self) -> None:
        selected_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        started_at = datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc)
        with patch.object(review_cycle, "current_time", return_value=selected_at):
            review_cycle.cmd_record_worker(
                args(
                    self.state_file,
                    worker_id="worker-1",
                    worker_profile="issue-worker",
                    worker_provider="openai",
                    worker_model="gpt-5",
                    continuity="worker_identity_profile",
                )
            )
        with patch.object(review_cycle, "current_time", return_value=started_at):
            review_cycle.cmd_start_implementation(
                args(
                    self.state_file,
                    worker_id="worker-1",
                    worker_profile="issue-worker",
                    worker_provider="openai",
                    worker_model="gpt-5",
                )
            )

        state = self.load()
        self.assertEqual(state["stage"], "implementing")
        self.assertEqual(state["implementation_started_at"], started_at.isoformat())
        self.assertEqual(state["history"][0]["kind"], "initialized")
        self.assertEqual(state["history"][1]["kind"], "worker_recorded")
        self.assertEqual(state["history"][2]["kind"], "implementation_started")
        self.assertEqual(state["history"][2]["worker_id"], "worker-1")
        self.assertEqual(state["history"][2]["worker_profile"], "issue-worker")
        self.assertEqual(state["history"][2]["worker_provider"], "openai")
        self.assertEqual(state["history"][2]["worker_model"], "gpt-5")

    def test_start_review_requires_recorded_worker(self) -> None:
        with self.assertRaisesRegex(SystemExit, "record the implementation worker before starting review"):
            review_cycle.cmd_start_review(
                args(
                    self.state_file,
                    reviewer_id="reviewer-1",
                    reviewer_profile="hermes-reviewer",
                )
            )

    def test_start_review_requires_start_implementation(self) -> None:
        review_cycle.cmd_record_worker(
            args(
                self.state_file,
                worker_id="worker-1",
                worker_profile="issue-worker",
                worker_provider="openai",
                worker_model="gpt-5",
                continuity="worker_identity_profile",
            )
        )
        with self.assertRaisesRegex(SystemExit, "start implementation before starting review"):
            review_cycle.cmd_start_review(
                args(
                    self.state_file,
                    reviewer_id="reviewer-1",
                    reviewer_profile="hermes-reviewer",
                )
            )

    def test_worker_continuity_requires_same_recorded_identity_and_profile(self) -> None:
        self.record_worker_and_start_implementation(
            worker_profile="openai-implementer",
            worker_provider="openai",
            worker_model="gpt-5",
        )

        review_cycle.cmd_start_review(
            args(
                self.state_file,
                reviewer_id="reviewer-1",
                reviewer_profile="hermes-reviewer",
            )
        )
        review_cycle.cmd_finish_review(
            args(
                self.state_file,
                outcome="changes",
                report="review-1.md",
                summary="one valid finding",
            )
        )
        with self.assertRaisesRegex(SystemExit, "worker identity/profile does not match"):
            review_cycle.cmd_record_fix(
                args(
                    self.state_file,
                    report="fix-1.md",
                    validation="tests passed",
                    worker_id="worker-2",
                    worker_profile="openai-implementer",
                    worker_provider="openai",
                    worker_model="gpt-5",
                )
            )
        review_cycle.cmd_record_fix(
            args(
                self.state_file,
                report="fix-1.md",
                validation="tests passed",
                worker_id="worker-1",
                worker_profile="openai-implementer",
                worker_provider="openai",
                worker_model="gpt-5",
            )
        )

        review_cycle.cmd_start_review(
            args(
                self.state_file,
                reviewer_id="reviewer-2",
                reviewer_profile="hermes-reviewer",
            )
        )
        review_cycle.cmd_finish_review(
            args(
                self.state_file,
                outcome="pass",
                report="review-2.md",
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
        ready_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        with patch.object(review_cycle, "current_time", return_value=ready_at):
            review_cycle.cmd_mark_ready(args(self.state_file))
        with patch.object(
            review_cycle,
            "current_time",
            return_value=ready_at + timedelta(seconds=review_cycle.REMOTE_WAIT_SECONDS),
        ):
            review_cycle.cmd_mark_feedback_fetched(
                args(self.state_file, snapshot="feedback.json")
            )
        with self.assertRaisesRegex(SystemExit, "worker identity/profile does not match"):
            review_cycle.cmd_record_remote_assessment(
                args(
                    self.state_file,
                    outcome="changes",
                    report="remote-review.md",
                    worker_id="worker-1",
                    worker_profile="anthropic-implementer",
                    worker_provider="openai",
                    worker_model="gpt-5",
                )
            )
        review_cycle.cmd_record_remote_assessment(
            args(
                self.state_file,
                outcome="changes",
                report="remote-review.md",
                worker_id="worker-1",
                worker_profile="openai-implementer",
                worker_provider="openai",
                worker_model="gpt-5",
            )
        )
        with self.assertRaisesRegex(SystemExit, "worker identity/profile does not match"):
            review_cycle.cmd_record_remote_fix(
                args(
                    self.state_file,
                    head_sha="def456",
                    validation="tests passed",
                    worker_id="worker-9",
                    worker_profile="openai-implementer",
                    worker_provider="openai",
                    worker_model="gpt-5",
                )
            )
        review_cycle.cmd_record_remote_fix(
            args(
                self.state_file,
                head_sha="def456",
                validation="tests passed",
                worker_id="worker-1",
                worker_profile="openai-implementer",
                worker_provider="openai",
                worker_model="gpt-5",
            )
        )

    def test_exact_session_worker_continuity_is_rejected(self) -> None:
        with self.assertRaisesRegex(SystemExit, "exact-session continuity is unsupported"):
            review_cycle.cmd_record_worker(
                args(
                    self.state_file,
                    worker_id="worker-1",
                    worker_profile="hermes-worker",
                    worker_provider="anthropic",
                    worker_model="claude-sonnet",
                    continuity="exact_session",
                )
            )

    def test_reviewer_identity_is_recorded_and_cannot_be_reused(self) -> None:
        self.record_worker_and_start_implementation(
            worker_profile="anthropic-worker",
            worker_provider="anthropic",
            worker_model="claude-sonnet",
        )
        review_cycle.cmd_start_review(
            args(
                self.state_file,
                reviewer_id="reviewer-1",
                reviewer_profile="profile-a",
            )
        )
        state = self.load()
        self.assertEqual(state["history"][-1]["kind"], "review_started")
        self.assertEqual(state["history"][-1]["reviewer_id"], "reviewer-1")
        self.assertEqual(state["history"][-1]["reviewer_profile"], "profile-a")

        review_cycle.cmd_abort_review(args(self.state_file, reason="spawn failed"))
        state = self.load()
        self.assertEqual(state["history"][-1]["kind"], "review_aborted")
        self.assertEqual(state["history"][-1]["reviewer_id"], "reviewer-1")
        self.assertEqual(state["history"][-1]["reviewer_profile"], "profile-a")

        with self.assertRaisesRegex(SystemExit, "reviewer identity was already used"):
            review_cycle.cmd_start_review(
                args(
                    self.state_file,
                    reviewer_id="reviewer-1",
                    reviewer_profile="profile-a",
                )
            )

        review_cycle.cmd_start_review(
            args(
                self.state_file,
                reviewer_id="reviewer-2",
                reviewer_profile="profile-a",
            )
        )
        review_cycle.cmd_finish_review(
            args(
                self.state_file,
                outcome="pass",
                report="review-1.md",
                summary="no findings",
            )
        )
        state = self.load()
        self.assertEqual(state["history"][-1]["kind"], "review_finished")
        self.assertEqual(state["history"][-1]["reviewer_id"], "reviewer-2")
        self.assertEqual(state["history"][-1]["reviewer_profile"], "profile-a")

    def test_record_worker_locks_provider_and_model_on_worker_driven_transitions(self) -> None:
        self.record_worker_and_start_implementation(
            worker_profile="anthropic-worker",
            worker_provider="anthropic",
            worker_model="claude-sonnet",
        )
        review_cycle.cmd_start_review(
            args(
                self.state_file,
                reviewer_id="reviewer-1",
                reviewer_profile="openai-reviewer",
            )
        )
        review_cycle.cmd_finish_review(
            args(
                self.state_file,
                outcome="changes",
                report="review-1.md",
                summary="one valid finding",
            )
        )
        with self.assertRaisesRegex(SystemExit, "worker provider/model does not match"):
            review_cycle.cmd_record_fix(
                args(
                    self.state_file,
                    worker_id="worker-1",
                    worker_profile="anthropic-worker",
                    worker_provider="openai",
                    worker_model="claude-sonnet",
                    report="fix-1.md",
                    validation="tests passed",
                )
            )
        with self.assertRaisesRegex(SystemExit, "worker provider/model does not match"):
            review_cycle.cmd_record_fix(
                args(
                    self.state_file,
                    worker_id="worker-1",
                    worker_profile="anthropic-worker",
                    worker_provider="anthropic",
                    worker_model="claude-opus",
                    report="fix-1.md",
                    validation="tests passed",
                )
            )
        review_cycle.cmd_record_fix(
            args(
                self.state_file,
                worker_id="worker-1",
                worker_profile="anthropic-worker",
                worker_provider="anthropic",
                worker_model="claude-sonnet",
                report="fix-1.md",
                validation="tests passed",
            )
        )

    def test_legacy_worker_can_be_enriched_once_then_locks_provider_and_model(self) -> None:
        state = self.load()
        state["worker"] = {
            "id": "worker-1",
            "profile": "issue-worker",
            "recorded_at": "2026-09-04T00:00:00+00:00",
        }
        state["needs_fix"] = True
        state["stage"] = "fixing"
        state["review_count"] = 1
        state["legacy_in_progress"] = True
        self.state_file.write_text(json.dumps(state), encoding="utf-8")

        with self.assertRaisesRegex(SystemExit, "enrich the recorded worker with provider and model first"):
            review_cycle.cmd_record_fix(
                args(
                    self.state_file,
                    worker_id="worker-1",
                    worker_profile="issue-worker",
                    worker_provider="openai",
                    worker_model="gpt-5",
                    report="fix-1.md",
                    validation="tests passed",
                )
            )

        review_cycle.cmd_record_worker(
            args(
                self.state_file,
                worker_id="worker-1",
                worker_profile="issue-worker",
                worker_provider="openai",
                worker_model="gpt-5",
                continuity="worker_identity_profile",
            )
        )
        enriched = review_cycle.cmd_status(args(self.state_file))
        self.assertEqual(enriched["worker"]["provider"], "openai")
        self.assertEqual(enriched["worker"]["model"], "gpt-5")
        review_cycle.cmd_record_fix(
            args(
                self.state_file,
                worker_id="worker-1",
                worker_profile="issue-worker",
                worker_provider="openai",
                worker_model="gpt-5",
                report="fix-1.md",
                validation="tests passed",
            )
        )

        with self.assertRaisesRegex(SystemExit, "implementation worker is already recorded"):
            review_cycle.cmd_record_worker(
                args(
                    self.state_file,
                    worker_id="worker-1",
                    worker_profile="issue-worker",
                    worker_provider="anthropic",
                    worker_model="claude-sonnet",
                    continuity="worker_identity_profile",
                )
            )

    def test_legacy_in_progress_state_is_detected_and_pending_fix_can_continue(self) -> None:
        state = self.load()
        state["worker"] = {
            "id": "worker-1",
            "profile": "issue-worker",
            "recorded_at": "2026-09-04T00:00:00+00:00",
        }
        state["review_count"] = 2
        state["needs_fix"] = True
        state["stage"] = "fixing"
        for key in ("implementation_started_at", "legacy_in_progress"):
            state.pop(key, None)
        self.state_file.write_text(json.dumps(state), encoding="utf-8")

        loaded = review_cycle.cmd_status(args(self.state_file))
        self.assertIsNone(loaded["implementation_started_at"])
        self.assertTrue(loaded["legacy_in_progress"])

        review_cycle.cmd_record_worker(
            args(
                self.state_file,
                worker_id="worker-1",
                worker_profile="issue-worker",
                worker_provider="openai",
                worker_model="gpt-5",
                continuity="worker_identity_profile",
            )
        )
        review_cycle.cmd_record_fix(
            args(
                self.state_file,
                worker_id="worker-1",
                worker_profile="issue-worker",
                worker_provider="openai",
                worker_model="gpt-5",
                report="fix-2.md",
                validation="tests passed",
            )
        )
        continued = review_cycle.cmd_status(args(self.state_file))
        self.assertTrue(continued["legacy_in_progress"])
        self.assertFalse(continued["needs_fix"])

    def test_record_check_repair_supports_issue_caused_failed_checks_before_remote_assessment(self) -> None:
        self.record_worker_and_start_implementation(
            worker_profile="issue-worker",
            worker_provider="openai",
            worker_model="gpt-5",
        )
        review_cycle.cmd_start_review(
            args(
                self.state_file,
                reviewer_id="reviewer-1",
                reviewer_profile="reviewer-profile",
            )
        )
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
        ready_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        with patch.object(review_cycle, "current_time", return_value=ready_at):
            review_cycle.cmd_mark_ready(args(self.state_file))
        review_cycle.cmd_record_checks(
            args(
                self.state_file,
                head_sha="abc123",
                result="fail",
                evidence="Issue-caused CI failure",
            )
        )

        with self.assertRaisesRegex(SystemExit, "worker provider/model does not match"):
            review_cycle.cmd_record_check_repair(
                args(
                    self.state_file,
                    worker_id="worker-1",
                    worker_profile="issue-worker",
                    worker_provider="anthropic",
                    worker_model="gpt-5",
                    head_sha="def456",
                    validation="targeted tests passed",
                    evidence="fixed CI failure",
                )
            )
        review_cycle.cmd_record_check_repair(
            args(
                self.state_file,
                worker_id="worker-1",
                worker_profile="issue-worker",
                worker_provider="openai",
                worker_model="gpt-5",
                head_sha="def456",
                validation="targeted tests passed",
                evidence="fixed CI failure",
            )
        )

        state = self.load()
        self.assertEqual(state["pr_head_sha"], "def456")
        self.assertFalse(state["checks_passed"])
        self.assertIsNone(state["checks_evidence"])
        self.assertEqual(state["remote_feedback_started_at"], ready_at.isoformat())
        self.assertIsNone(state["remote_feedback_fetched_at"])
        self.assertEqual(state["stage"], "pr_ready")
        self.assertEqual(state["check_repair_count"], 1)
        self.assertEqual(state["check_repairs"][0]["previous_head_sha"], "abc123")
        self.assertEqual(state["check_repairs"][0]["head_sha"], "def456")

    def test_record_check_repair_requires_failed_current_head_and_new_head(self) -> None:
        self.record_worker_and_start_implementation(
            worker_profile="issue-worker",
            worker_provider="openai",
            worker_model="gpt-5",
        )
        review_cycle.cmd_start_review(
            args(
                self.state_file,
                reviewer_id="reviewer-1",
                reviewer_profile="reviewer-profile",
            )
        )
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

        with self.assertRaisesRegex(SystemExit, "failed checks on the current PR HEAD"):
            review_cycle.cmd_record_check_repair(
                args(
                    self.state_file,
                    worker_id="worker-1",
                    worker_profile="issue-worker",
                    worker_provider="openai",
                    worker_model="gpt-5",
                    head_sha="def456",
                    validation="targeted tests passed",
                    evidence="fixed CI failure",
                )
            )

        review_cycle.cmd_record_checks(
            args(
                self.state_file,
                head_sha="abc123",
                result="fail",
                evidence="Issue-caused CI failure",
            )
        )
        with self.assertRaisesRegex(SystemExit, "must record a new PR HEAD SHA"):
            review_cycle.cmd_record_check_repair(
                args(
                    self.state_file,
                    worker_id="worker-1",
                    worker_profile="issue-worker",
                    worker_provider="openai",
                    worker_model="gpt-5",
                    head_sha="abc123",
                    validation="targeted tests passed",
                    evidence="fixed CI failure",
                )
            )

    def test_record_decision_appends_line_and_history_event(self) -> None:
        log_path = review_cycle.decisions_log_path(args(self.state_file))
        review_cycle.cmd_record_decision(
            args(
                self.state_file,
                point="review-1 finding accept",
                outcome="accept",
                reason="reproducible data-contract bug mapped to AC-2",
            )
        )

        lines = [
            line
            for line in log_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(len(lines), 1)
        record = json.loads(lines[0])
        self.assertEqual(record["point"], "review-1 finding accept")
        self.assertEqual(record["outcome"], "accept")
        self.assertEqual(record["reason"], "reproducible data-contract bug mapped to AC-2")
        # `at` is present and a valid ISO timestamp
        datetime.fromisoformat(record["at"])

        state = self.load()
        self.assertEqual(state["history"][-1]["kind"], "decision_recorded")
        self.assertEqual(state["history"][-1]["point"], "review-1 finding accept")
        self.assertEqual(state["history"][-1]["outcome"], "accept")

    def test_record_decision_is_append_only(self) -> None:
        log_path = review_cycle.decisions_log_path(args(self.state_file))
        review_cycle.cmd_record_decision(
            args(self.state_file, point="finding 1", outcome="reject", reason="speculative")
        )
        review_cycle.cmd_record_decision(
            args(self.state_file, point="round 1", outcome="changes", reason="one valid finding")
        )

        lines = [
            line
            for line in log_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0])["point"], "finding 1")
        self.assertEqual(json.loads(lines[1])["point"], "round 1")
        self.assertEqual(json.loads(lines[1])["outcome"], "changes")

    def test_show_decisions_reads_back_content(self) -> None:
        empty_buf = io.StringIO()
        with contextlib.redirect_stdout(empty_buf):
            review_cycle.cmd_show_decisions(args(self.state_file))
        self.assertIn("no decisions", empty_buf.getvalue())

        review_cycle.cmd_record_decision(
            args(
                self.state_file,
                point="remote comment #3",
                outcome="invalid",
                reason="policy-excluded speculative item",
            )
        )
        review_cycle.cmd_record_decision(
            args(
                self.state_file,
                point="blocked resolution",
                outcome="merge",
                reason="controller decision with evidence",
            )
        )

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            review_cycle.cmd_show_decisions(args(self.state_file))
        output = buf.getvalue()
        self.assertIn("remote comment #3", output)
        self.assertIn("invalid", output)
        self.assertIn("blocked resolution", output)
        self.assertIn("merge", output)


class SkillMetadataTests(unittest.TestCase):
    def test_skill_name_and_invocation_are_consistent(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        prompt = (ROOT / "references" / "issue-manager-prompt.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        readme_zh = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")

        self.assertIn("name: issue-to-merge", skill)
        self.assertIn("`issue-to-merge` skill", prompt)
        self.assertIn("README.zh-CN.md", readme)
        self.assertIn("README.md", readme_zh)
        self.assertNotIn("managed-pr-development", skill + prompt)

    def test_review_policy_reaches_local_remote_and_user_facing_paths(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        prompt = (ROOT / "references" / "issue-manager-prompt.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        readme_zh = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")

        policy = skill.split("## Default review policy", 1)[1].split(
            "## User-facing communication", 1
        )[0]
        self.assertIn("realistically reproducible", policy)
        self.assertIn("functionality, workflow, a data contract, or error handling", policy)
        self.assertIn("numbered Issue acceptance criterion", policy)
        self.assertIn("general security hardening", policy)
        self.assertIn("speculative refactors", policy)
        self.assertIn("No implementation or fix may introduce a security framework", policy)
        self.assertIn("Required checks are separate merge gates, not findings", policy)

        local_review = skill.split("### 3. Run the bounded local-review loop", 1)[1].split(
            "### 4. Publish", 1
        )[0]
        remote_review = skill.split("### 5. Handle one remote-feedback window", 1)[1].split(
            "### 6. Merge", 1
        )[0]
        self.assertIn("default review policy", local_review)
        self.assertIn("same numbered acceptance criteria", remote_review)
        self.assertIn("same realistic-reproduction", remote_review)
        self.assertIn("do not classify them as findings", remote_review)

        self.assertIn("default review policy supplied to local reviewers", prompt)
        self.assertIn("<EXACT_TOP_LEVEL_USER_INSTRUCTION_OR_NONE>", prompt)
        self.assertIn("must not introduce a security framework", prompt)
        self.assertIn("Required-check results stay with the manager", prompt)
        self.assertIn("match the user's language", skill)
        self.assertIn("match the user's language", prompt)
        self.assertIn("Remote comments pass through the same finding policy", readme)
        self.assertIn("远程 comments 必须通过与本地审核相同的 finding 标准", readme_zh)

    def test_waste_prevention_guards_reach_their_owning_roles(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        prompt = (ROOT / "references" / "issue-manager-prompt.md").read_text(
            encoding="utf-8"
        )

        controller = skill.split("## Program Controller", 1)[1].split(
            "## Issue Task Manager", 1
        )[0]
        scope = skill.split("### 1. Establish scope", 1)[1].split(
            "### 2. Dispatch implementation", 1
        )[0]
        implementation = skill.split("### 2. Dispatch implementation", 1)[1].split(
            "### 3. Run the bounded local-review loop", 1
        )[0]
        remote = skill.split("### 5. Handle one remote-feedback window", 1)[1].split(
            "### 6. Merge and clean up", 1
        )[0]
        manager_template = prompt.split("```text", 1)[1].split("```", 1)[0]
        worker_fields = prompt.split("## Mandatory worker-prompt fields", 1)[1].split(
            "## Mandatory reviewer-prompt fields", 1
        )[0]

        self.assertIn("search open and closed PRs plus remote branches", controller)
        self.assertIn("do not create a duplicate", controller)
        self.assertIn("reproduce the reported behavior", scope)
        self.assertIn("git log -S", scope)
        self.assertIn("intentional or the Issue is stale", scope)
        self.assertIn("sibling call sites", implementation)
        self.assertIn("pre-fix behavior", implementation)
        self.assertIn("Feature-only work does not require", implementation)
        self.assertIn("Do not broaden the change", implementation)
        self.assertIn("attribute the failure before attempting a repair", remote)
        self.assertIn("Issue diff", remote)
        self.assertIn("default-branch baseline", remote)
        self.assertIn("transient infrastructure failure", remote)
        self.assertIn("Re-run a failed check at most once", remote)

        self.assertIn("<PR_AND_REMOTE_BRANCH_SEARCH_EVIDENCE>", manager_template)
        self.assertIn("reproduce the reported behavior", manager_template)
        self.assertIn("same-shaped sibling call sites", manager_template)
        self.assertIn("Feature-only work is exempt", manager_template)
        self.assertIn("attribute it before repair", manager_template)
        self.assertIn("Re-run once without a code change", manager_template)
        self.assertIn("record-check-repair", manager_template)
        self.assertIn("start-implementation", manager_template)

        self.assertIn("same-shaped sibling sites to inspect", worker_fields)
        self.assertIn("expected pre-fix failure and post-fix pass evidence", worker_fields)
        self.assertIn("feature-only work is exempt", worker_fields)
        self.assertIn("provider", worker_fields)
        self.assertIn("model", worker_fields)
        self.assertNotIn("attribute it before repair", worker_fields)

    def test_each_issue_uses_one_closable_task_and_fresh_reviewers(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        prompt = (ROOT / "references" / "issue-manager-prompt.md").read_text(
            encoding="utf-8"
        )
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        readme_zh = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")

        controller = skill.split("## Program Controller", 1)[1].split(
            "## Issue Task Manager", 1
        )[0]
        implementation = skill.split("### 2. Dispatch implementation", 1)[1].split(
            "### 3. Run the bounded local-review loop", 1
        )[0]
        local_review = skill.split("### 3. Run the bounded local-review loop", 1)[
            1
        ].split("### 4. Publish", 1)[0]
        remote = skill.split("### 5. Handle one remote-feedback window", 1)[1].split(
            "### 6. Merge and clean up", 1
        )[0]
        quality = skill.split("## Quality Gates", 1)[1].split(
            "## User-facing progress shape", 1
        )[0]
        manager_template = prompt.split("```text", 1)[1].split("```", 1)[0]

        self.assertIn("fresh top-level Issue task", controller)
        self.assertIn("root agent is the Issue manager", controller)
        self.assertIn("close the completed Issue task", controller)
        self.assertIn("before starting the next Issue", controller)
        self.assertNotIn("spawn a **new dedicated issue-manager subagent**", controller)

        self.assertIn("one fresh worker subagent", implementation)
        self.assertIn("same worker for the entire Issue", implementation)
        self.assertIn("release that one-shot reviewer", local_review)
        self.assertIn("Never reuse a local reviewer", local_review)
        self.assertIn("same Issue worker", remote)
        self.assertNotIn("new remote-feedback worker", remote)
        self.assertIn("Issue task was closed", quality)

        self.assertIn("top-level task", manager_template)
        self.assertIn("Do not create another manager agent", manager_template)
        self.assertIn("same implementation worker for the entire Issue", manager_template)
        self.assertIn("release that one-shot reviewer", manager_template)
        self.assertIn("same worker", manager_template)
        self.assertIn("mark-task-closed", prompt)

        self.assertIn("top-level task", readme)
        self.assertIn("关闭当前 Issue 任务", readme_zh)

        self.assertNotIn("close_agent", skill + prompt)

    def test_skill_workflow_includes_required_identity_flags(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        local_review = skill.split("### 3. Run the bounded local-review loop", 1)[
            1
        ].split("### 4. Publish", 1)[0]

        self.assertIn("`start-review --reviewer-id", local_review)
        self.assertIn("--reviewer-profile", local_review)
        self.assertIn("`record-fix --worker-id", local_review)
        self.assertIn("--worker-profile", local_review)
        self.assertIn("--worker-provider", local_review)
        self.assertIn("--worker-model", local_review)

    def test_model_configuration_is_documented_and_shipped(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        config_path = ROOT / "config" / "models.json"

        self.assertIn("config/models.json", skill)
        self.assertIn("fall back to the agent's own current model", skill)

        self.assertTrue(config_path.is_file())
        config = json.loads(config_path.read_text(encoding="utf-8"))
        for role in ("manager", "worker", "reviewer", "remote_worker"):
            self.assertIn(role, config)

    def test_verification_only_delivery_is_a_first_class_terminal_state(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        pattern_path = ROOT / "references" / "acceptance-already-implemented-pattern.md"

        quality = skill.split("## Quality Gates", 1)[1].split(
            "## User-facing progress shape", 1
        )[0]
        self.assertIn("Code-change delivery", quality)
        self.assertIn("Verification-only delivery", quality)

        self.assertTrue(pattern_path.is_file())
        self.assertGreater(len(pattern_path.read_text(encoding="utf-8").strip()), 0)

    def test_hermes_runtime_adaptation_is_documented_and_linked(self) -> None:
        doc_path = ROOT / "references" / "hermes-runtime.md"
        adapter_path = ROOT / "references" / "hermes-profiles-kanban.md"
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        readme_zh = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")

        self.assertTrue(doc_path.is_file())
        self.assertTrue(adapter_path.is_file())
        doc = doc_path.read_text(encoding="utf-8")
        adapter = adapter_path.read_text(encoding="utf-8")
        self.assertGreater(len(doc.strip()), 0)
        self.assertGreater(len(adapter.strip()), 0)

        # Issue #12 requires the document to actually cover the four Hermes runtime
        # adaptations, not merely exist as an empty shell. Assert each section's
        # key phrase is present so future edits cannot silently drop a section.
        # 1. Default flat hierarchy; higher max_spawn_depth can permit nesting.
        self.assertIn("Flatten the role hierarchy", doc)
        self.assertIn("max_spawn_depth: 1", doc)
        self.assertIn("higher configured depth can permit orchestrator nesting", doc)
        self.assertIn("worker and reviewers must not delegate further", doc)
        # 2. Respect the ~600s delegate timeout.
        self.assertIn("600", doc)
        self.assertIn("timeout", doc)
        # 3. Bootstrap new commands from the worktree's state script.
        self.assertIn("state script", doc)
        self.assertIn("worktree", doc)
        # 4. Avoid `python3 | python3` pipelines.
        self.assertIn("pipeline", doc)
        self.assertIn("hermes-profiles-kanban.md", doc)
        self.assertIn("worker_identity_profile", adapter)
        self.assertIn("exact session continuity", adapter.casefold())
        self.assertIn("same durable card/task handle", adapter)
        self.assertIn("complete durable task context", adapter)
        self.assertIn("kanban_show", adapter)
        self.assertIn("record-worker", adapter)
        self.assertIn("start-implementation", adapter)
        self.assertIn("audits declared lifecycle order", adapter)
        self.assertIn("cannot observe arbitrary out-of-band file edits", adapter)
        self.assertIn("current diff/test evidence", adapter)
        self.assertIn("fail closed", adapter)
        self.assertIn("profiles own config/provider/model", adapter)
        self.assertIn("config/models.json", adapter)
        self.assertIn("selected profile is authoritative", adapter)
        self.assertIn("null role-model config leaves it unchanged", adapter)
        self.assertIn("max_spawn_depth", adapter)
        self.assertIn("worker/reviewer remain leaves", adapter)

        runtime_compat = readme.split("## Runtime compatibility", 1)[1].split(
            "## Design boundary", 1
        )[0]
        self.assertIn("hermes-runtime.md", runtime_compat)
        self.assertIn("hermes-profiles-kanban.md", runtime_compat)

        runtime_compat_zh = readme_zh.split("## 运行时兼容性", 1)[1].split(
            "## 设计边界", 1
        )[0]
        self.assertIn("hermes-runtime.md", runtime_compat_zh)
        self.assertIn("hermes-profiles-kanban.md", runtime_compat_zh)


if __name__ == "__main__":
    unittest.main()
