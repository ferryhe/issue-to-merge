"""Exercise optional Copilot without making GitHub or TypeSafe requests."""
import importlib.util
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(os.environ.get("ISSUE_TO_MERGE_SCRIPT", Path(__file__).resolve().parents[1] / "scripts/review_cycle.py"))
SPEC = importlib.util.spec_from_file_location("optional_copilot_cycle", SCRIPT)
cycle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cycle)


class CopilotOptionsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.worker = dict(worker_id="worker", worker_profile="worker", worker_provider="codex", worker_model="gpt-6-luna", worker_reasoning="high")

    def call(self, command, **values):
        parser = cycle.build_parser()
        options = parser._subparsers._group_actions[0].choices[command]._option_string_actions
        argv = [command, "--state-file", str(self.state)]
        for key, value in values.items():
            flag = "--" + key.replace("_", "-")
            if flag in options:
                argv.extend((flag, str(value)))
        args = parser.parse_args(argv)
        return args.handler(args)

    def load(self):
        return json.loads(self.state.read_text(encoding="utf-8"))

    def review(self):
        number = self.load()["review_count"] + 1
        self.call("start-review", reviewer_id=f"reviewer-{number}", reviewer_profile="reviewer")
        if self.load().get("typesafe_required"):
            report = self.directory / "local-typesafe.json"
            report.write_text(json.dumps(dict(schema_version=1, question_set="issue-to-merge-typesafe-review-v1", requested_model="jev-latest", review_kind="local")))
            self.call("record-typesafe-review", report=report)
        self.call("finish-review", outcome="pass", report="review.md", summary="fixture has no mapped findings")

    def ready(self, mode, copilot=None):
        self.state = self.directory / f"{mode}-{copilot}.json"
        options = {} if copilot is None else dict(copilot=copilot)
        self.call("init", issue="42", branch="agent/issue-42", manager_id="manager", mode=mode, **options)
        if hasattr(cycle, "cmd_record_worker"):
            self.call("record-worker", **self.worker, continuity="worker_identity_profile")
            self.call("start-implementation", **self.worker)
        self.review()
        self.call("record-pr", url="https://example.test/repo/pull/1", head_sha="head-1", closing_reference="Closes #42")
        self.call("mark-ready")

    def assess(self, outcome="clean"):
        options = {}
        if self.load().get("typesafe_required"):
            report = self.directory / "remote-typesafe.json"
            report.write_text(json.dumps(dict(schema_version=1, question_set="issue-to-merge-typesafe-review-v1", requested_model="jev-latest", review_kind="remote")))
            options["typesafe_report"] = report
        self.call("record-remote-assessment", outcome=outcome, report="remote.md", **options, **self.worker)

    def unavailable(self, head="head-1", reason="GitHub reported review unavailable"):
        evidence = self.directory / "copilot-unavailable.json"
        evidence.write_text(json.dumps(dict(pr_url=self.load()["pr_url"], head_sha=head, code_review_completed=False, reason=reason)))
        return self.call("record-copilot-unavailable", head_sha=head, evidence=evidence)

    def test_auto_is_default_and_requires_real_completion_in_both_modes(self):
        for mode in ("full", "quick"):
            with self.subTest(mode=mode):
                self.ready(mode)
                self.assertEqual(self.load()["copilot_mode"], "auto")
                self.call("record-copilot-request", head_sha="head-1", evidence="GitHub accepted review request")
                after = datetime.fromisoformat(self.load()["copilot_review_started_at"]) + timedelta(seconds=601)
                with patch.object(cycle, "current_time", return_value=after):
                    with self.assertRaisesRegex(SystemExit, "copilot-review"):
                        self.call("mark-feedback-fetched", snapshot="feedback.json")
                    self.call("mark-feedback-fetched", snapshot="feedback.json", copilot_review_head="head-1", copilot_review_evidence="completed review proof")
                self.assertIn("copilot_review_completed", [event["kind"] for event in self.load()["history"]])

    def test_off_skips_request_and_timer_but_keeps_checks_in_both_modes(self):
        for mode in ("full", "quick"):
            with self.subTest(mode=mode):
                self.ready(mode, "off")
                with self.assertRaisesRegex(SystemExit, "disabled"):
                    self.call("record-copilot-request", head_sha="head-1", evidence="unwanted request")
                self.call("mark-feedback-fetched", snapshot="feedback.json")
                self.assess()
                self.call("record-checks", head_sha="head-1", result="fail", evidence="CI failed")
                with self.assertRaisesRegex(SystemExit, "passing required checks"):
                    self.call("mark-merged", merge_sha="merge", evidence="merge")
                self.call("record-checks", head_sha="head-1", result="pass", evidence="CI passed")
                if hasattr(cycle, "cmd_record_review_threads"):
                    self.call("record-review-threads", head_sha="head-1", unresolved_count=0, evidence="fresh query")
                self.call("mark-merged", merge_sha="merge", evidence="merge proof")
                self.assertNotIn("copilot_review_completed", [event["kind"] for event in self.load()["history"]])

    def test_unavailable_before_request_needs_no_extra_authorization(self):
        for mode in ("full", "quick"):
            with self.subTest(mode=mode):
                self.ready(mode, "auto")
                self.unavailable()
                self.call("mark-feedback-fetched", snapshot="feedback.json")
                self.assertFalse(self.load().get("copilot_review_requests"))
                with self.assertRaisesRegex(SystemExit, "disabled"):
                    self.call("record-copilot-request", head_sha="head-1", evidence="unwanted retry")
                self.assertNotIn("copilot_review_completed", [event["kind"] for event in self.load()["history"]])

    def test_remote_typesafe_report_requires_a_selected_strict_typesafe_route(self):
        for mode in ("full", "quick"):
            with self.subTest(mode=mode):
                self.ready(mode, "off")
                self.call("mark-feedback-fetched", snapshot="feedback.json")
                report = self.directory / "unselected-typesafe.json"
                report.write_text("{}")
                before = self.state.read_bytes()
                with self.assertRaisesRegex(SystemExit, "strict typesafe-ai Judge"):
                    self.call("record-remote-assessment", outcome="clean", report="remote.md", typesafe_report=report, **self.worker)
                self.assertEqual(before, self.state.read_bytes())

    def test_unavailable_after_request_skips_remaining_window(self):
        self.ready("quick", "auto")
        self.call("record-copilot-request", head_sha="head-1", evidence="request accepted")
        self.unavailable()
        self.call("mark-feedback-fetched", snapshot="feedback.json")
        self.assertEqual(self.load()["copilot_unavailable"]["head_sha"], "head-1")

    def test_completed_feedback_cannot_be_reclassified_as_unavailable(self):
        for mode in ("full", "quick"):
            with self.subTest(mode=mode):
                self.ready(mode, "auto")
                self.call("record-copilot-request", head_sha="head-1", evidence="initial request")
                after = datetime.fromisoformat(self.load()["copilot_review_started_at"]) + timedelta(seconds=601)
                with patch.object(cycle, "current_time", return_value=after):
                    self.call("mark-feedback-fetched", snapshot="feedback.json", copilot_review_head="head-1", copilot_review_evidence="completed review")
                self.assess()
                before = self.state.read_bytes()
                with self.assertRaisesRegex(SystemExit, "feedback was already fetched"):
                    self.unavailable()
                self.assertEqual(before, self.state.read_bytes())

    def test_unavailable_evidence_for_another_head_is_rejected(self):
        self.ready("quick", "auto")
        evidence = self.directory / "stale.json"
        evidence.write_text(json.dumps(dict(pr_url=self.load()["pr_url"], head_sha="old-head", code_review_completed=False, reason="unavailable")))
        before = self.state.read_bytes()
        with self.assertRaisesRegex(SystemExit, "current PR HEAD"):
            self.call("record-copilot-unavailable", head_sha="head-1", evidence=evidence)
        self.assertEqual(before, self.state.read_bytes())

    def test_quick_material_fix_with_off_still_requires_local_review(self):
        self.ready("quick", "off")
        self.call("mark-feedback-fetched", snapshot="feedback.json")
        self.assess("changes")
        self.call("record-remote-fix", head_sha="head-2", report="fix.md", validation="tests passed", review_impact="material", impact_evidence="behavior changed", **self.worker)
        self.assertFalse(self.load()["local_review_closed"])
        self.assertFalse(self.load()["copilot_review_pending"])
        self.review()
        self.assertTrue(self.load()["local_review_closed"])
        self.assertFalse(self.load()["checks_passed"])

    def test_material_fix_keeps_one_request_and_feedback_in_both_modes(self):
        for mode in ("full", "quick"):
            with self.subTest(mode=mode):
                self.ready(mode, "auto")
                self.call("record-copilot-request", head_sha="head-1", evidence="initial request")
                after = datetime.fromisoformat(self.load()["copilot_review_started_at"]) + timedelta(seconds=601)
                with patch.object(cycle, "current_time", return_value=after):
                    self.call("mark-feedback-fetched", snapshot="initial-feedback.json", copilot_review_head="head-1", copilot_review_evidence="completed first review")
                self.assess("changes")
                self.call("record-remote-fix", head_sha="head-2", report="fix.md", validation="tests passed", review_impact="material", impact_evidence="behavior changed", **self.worker)
                if mode == "quick":
                    self.review()
                with self.assertRaisesRegex(SystemExit, "only once per PR"):
                    self.call("record-copilot-request", head_sha="head-2", evidence="unwanted repeat")
                with self.assertRaisesRegex(SystemExit, "already fetched"):
                    self.call("mark-feedback-fetched", snapshot="unwanted-repeat.json")
                state = self.load()
                self.assertEqual(state["remote_feedback_snapshot"], "initial-feedback.json")
                self.assertEqual(state["remote_assessment"]["outcome"], "changes")
                self.assertFalse(state["copilot_review_pending"])
                self.assertFalse(state["checks_passed"])
                self.assertEqual(len(state["copilot_review_requests"]), 1)
                self.assertEqual(sum(event["kind"] == "remote_feedback_fetched" for event in state["history"]), 1)

    def test_full_check_repair_records_new_head_and_invalidates_checks(self):
        self.ready("full", "off")
        self.call("record-checks", head_sha="head-1", result="fail", evidence="Issue-caused failure")
        result = self.call("record-check-repair", head_sha="head-2", validation="tests passed", evidence="baseline passes, regression fixed", **self.worker)
        self.assertEqual(result["pr_head_sha"], "head-2")
        self.assertFalse(result["checks_passed"])
        self.assertTrue(result["local_review_closed"])

    def test_first_request_cannot_start_after_a_repair_push(self):
        for mode in ("full", "quick"):
            with self.subTest(mode=mode):
                self.ready(mode, "auto")
                self.call("record-checks", head_sha="head-1", result="fail", evidence="Issue-caused test failure")
                self.call("record-check-repair", head_sha="head-2", validation="tests passed", evidence="test-only repair", review_impact="none", impact_evidence="test-only correction", **self.worker)
                before = self.state.read_bytes()
                with self.assertRaisesRegex(SystemExit, "initial PR publication"):
                    self.call("record-copilot-request", head_sha="head-2", evidence="late first request")
                self.assertEqual(before, self.state.read_bytes())
                self.unavailable("head-2", reason="Initial publication window passed; later requests are not allowed")
                self.call("mark-feedback-fetched", snapshot="feedback-without-copilot.json")

    def test_legacy_ready_history_preserves_the_initial_request_boundary(self):
        for mode in ("full", "quick"):
            with self.subTest(mode=mode):
                self.ready(mode, "auto")
                state = self.load()
                del state["ready_head_sha"]
                self.state.write_text(json.dumps(state))
                self.call("record-copilot-request", head_sha="head-1", evidence="initial request")
                self.assertEqual(self.load()["copilot_review_requests"][0]["head_sha"], "head-1")

    def test_legacy_state_keeps_its_existing_feedback_contract(self):
        for mode in ("full", "quick"):
            with self.subTest(mode=mode):
                self.ready(mode)
                if mode == "quick":
                    self.call("record-copilot-request", head_sha="head-1", evidence="existing request")
                state = self.load()
                del state["copilot_mode"]
                self.state.write_text(json.dumps(state))
                with self.assertRaisesRegex(SystemExit, "seconds remaining"):
                    self.call("mark-feedback-fetched", snapshot="too-early.json")
                started = state.get("copilot_review_started_at") or state["remote_feedback_started_at"]
                after = datetime.fromisoformat(started) + timedelta(seconds=601)
                proof = {} if mode == "full" else dict(copilot_review_head="head-1", copilot_review_evidence="existing completion")
                with patch.object(cycle, "current_time", return_value=after):
                    self.call("mark-feedback-fetched", snapshot="feedback.json", **proof)


if __name__ == "__main__":
    unittest.main()
