"""Run against the checkout or an installed script via ISSUE_TO_MERGE_SCRIPT."""
import importlib.util
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(os.environ.get("ISSUE_TO_MERGE_SCRIPT", Path(__file__).resolve().parents[1] / "scripts/review_cycle.py"))
SPEC = importlib.util.spec_from_file_location("quick_review_cycle", SCRIPT)
cycle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cycle)


class QuickModeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name) / "state.json"
        self.worker = dict(worker_id="worker", worker_profile="worker", worker_provider="codex", worker_model="gpt-6-luna", worker_reasoning="high")
        self.run_cmd("init", issue="42", branch="codex/issue-42", manager_id="manager", mode="quick")
        if hasattr(cycle, "cmd_record_worker"):
            self.run_cmd("record-worker", **self.worker, continuity="worker_identity_profile")
            self.run_cmd("start-implementation", **self.worker)

    def run_cmd(self, command, **values):
        parser = cycle.build_parser()
        subparser = parser._subparsers._group_actions[0].choices[command]
        options = subparser._option_string_actions
        argv = [command, "--state-file", str(self.state)]
        for key, value in values.items():
            flag = "--" + key.replace("_", "-")
            if flag in options:
                argv.extend([flag, str(value)])
        args = parser.parse_args(argv)
        return args.handler(args)

    def load(self):
        return json.loads(self.state.read_text())

    def review(self, outcome="pass"):
        count = self.load()["review_count"] + 1
        self.run_cmd("start-review", reviewer_id=f"reviewer-{count}", reviewer_profile="reviewer")
        if self.load().get("typesafe_required"):
            report = Path(self.temp.name) / "typesafe.json"
            report.write_text(json.dumps(dict(schema_version=1, question_set="issue-to-merge-typesafe-review-v1", requested_model="jev-latest", review_kind="local")))
            self.run_cmd("record-typesafe-review", report=report)
        return self.run_cmd("finish-review", outcome=outcome, report="review.md", summary="concrete acceptance evidence")

    def publish(self):
        self.run_cmd("record-pr", url="https://github.com/example/repo/pull/1", head_sha="head-1", closing_reference="Closes #42")
        self.run_cmd("mark-ready")

    def fetch(self):
        if not self.load().get("copilot_review_requests"):
            self.run_cmd("record-copilot-request", head_sha=self.load()["pr_head_sha"], evidence="initial automatic request proof")
        stamp = self.load().get("copilot_review_started_at") or self.load()["remote_feedback_started_at"]
        after = datetime.fromisoformat(stamp) + timedelta(seconds=600)
        with patch.object(cycle, "current_time", return_value=after):
            self.run_cmd("mark-feedback-fetched", snapshot="feedback.json", copilot_review_head=self.load()["copilot_review_requests"][-1]["head_sha"], copilot_review_evidence="completed review proof")

    def assess(self, outcome="clean"):
        options = {}
        if self.load().get("typesafe_required"):
            report = Path(self.temp.name) / "remote-typesafe.json"
            report.write_text(json.dumps(dict(schema_version=1, question_set="issue-to-merge-typesafe-review-v1", requested_model="jev-latest", review_kind="remote")))
            options["typesafe_report"] = report
        self.run_cmd("record-remote-assessment", outcome=outcome, report="remote.md", **options, **self.worker)

    def fix(self, command="record-fix", impact="none", **extra):
        return self.run_cmd(command, report="fix.md", validation="focused tests pass", review_impact=impact, impact_evidence="diff and fixture results", **self.worker, **extra)

    def test_small_local_fix_needs_only_one_review(self):
        self.review("changes")
        result = self.fix()
        self.assertTrue(result["local_review_closed"])
        self.assertEqual(result["review_count"], 1)
        self.assertEqual(result["last_review_outcome"], "changes")
        self.assertFalse(result["final_unreviewed_fix"])
        self.publish()

    def test_material_local_fix_requires_another_review(self):
        self.review("changes")
        self.fix(impact="material")
        with self.assertRaisesRegex(SystemExit, "local review"):
            self.publish()
        self.review()
        self.publish()
        self.assertEqual(self.load()["review_count"], 2)

    def test_impact_evidence_is_required(self):
        self.review("changes")
        before = self.state.read_bytes()
        with self.assertRaises(SystemExit):
            self.run_cmd("record-fix", report="fix.md", validation="passed", **self.worker)
        self.assertEqual(self.state.read_bytes(), before)

    def test_material_remote_fix_needs_local_review_without_repeat_copilot(self):
        self.review()
        self.publish()
        self.run_cmd("record-copilot-request", head_sha="head-1", evidence="initial request")
        self.fetch()
        self.assess("changes")
        self.fix("record-remote-fix", "material", head_sha="head-2")
        self.run_cmd("record-checks", head_sha="head-2", result="pass", evidence="checks")
        with self.assertRaisesRegex(SystemExit, "local review"):
            self.run_cmd("mark-merged", merge_sha="merge", evidence="merge")
        self.review()
        with self.assertRaisesRegex(SystemExit, "only once per PR"):
            self.run_cmd("record-copilot-request", head_sha="head-2", evidence="unwanted repeat")
        if hasattr(cycle, "cmd_record_review_threads"):
            self.run_cmd("record-review-threads", head_sha="head-2", unresolved_count=0, evidence="fresh query")
        self.run_cmd("mark-merged", merge_sha="merge", evidence="merge")
        self.assertEqual(self.load()["review_count"], 2)
        self.assertEqual(len(self.load()["copilot_review_requests"]), 1)

    def test_small_remote_fix_does_not_reopen_reviews(self):
        self.review()
        self.publish()
        self.fetch()
        self.assess("changes")
        self.fix("record-remote-fix", head_sha="head-2")
        self.assertTrue(self.load()["local_review_closed"])
        self.assertFalse(self.load().get("copilot_review_pending", False))
        with self.assertRaises(SystemExit):
            self.run_cmd("record-copilot-request", head_sha="head-2", evidence="unnecessary request")

    def test_wrong_head_and_duplicate_copilot_request_are_rejected(self):
        self.review()
        self.publish()
        with self.assertRaisesRegex(SystemExit, "current PR HEAD"):
            self.run_cmd("record-copilot-request", head_sha="stale", evidence="request")
        self.run_cmd("record-copilot-request", head_sha="head-1", evidence="request")
        with self.assertRaises(SystemExit):
            self.run_cmd("record-copilot-request", head_sha="head-1", evidence="duplicate")

    def test_final_review_material_fix_closes_without_another_review(self):
        self.review("changes")
        state = self.load()
        state["max_reviews"] = 1
        self.state.write_text(json.dumps(state))
        result = self.fix(impact="material")
        self.assertFalse(result["needs_fix"])
        self.assertTrue(result["local_review_closed"])
        self.assertTrue(result["final_unreviewed_fix"])
        self.assertEqual(result["last_review_outcome"], "changes")
        self.assertEqual(result["review_count"], 1)
        with self.assertRaisesRegex(SystemExit, "already closed"):
            self.run_cmd("start-review", reviewer_id="extra", reviewer_profile="reviewer")
        self.publish()

    def test_material_remote_fix_at_limit_still_requires_review(self):
        self.review()
        self.publish()
        self.fetch()
        self.assess("changes")
        state = self.load()
        state["max_reviews"] = 1
        self.state.write_text(json.dumps(state))
        before = self.state.read_bytes()
        with self.assertRaisesRegex(SystemExit, "review limit"):
            self.fix("record-remote-fix", "material", head_sha="head-2")
        self.assertEqual(self.state.read_bytes(), before)

    def test_material_check_repair_before_feedback_can_be_reviewed(self):
        self.review()
        self.publish()
        self.run_cmd("record-copilot-request", head_sha="head-1", evidence="initial PR request")
        self.run_cmd("record-checks", head_sha="head-1", result="fail", evidence="Issue-caused failure")
        self.fix("record-check-repair", "material", head_sha="head-2", evidence="baseline pass and new regression fail")
        self.review()
        self.assertEqual(self.load()["stage"], "pr_ready")
        self.fetch()
        self.assess()

    def test_local_fix_after_remote_re_review_tracks_new_head(self):
        self.review()
        self.publish()
        self.fetch()
        self.assess("changes")
        self.fix("record-remote-fix", "material", head_sha="head-2")
        self.review("changes")
        self.fix(head_sha="head-3")
        self.assertEqual(self.load()["stage"], "merge_ready")
        self.assertFalse(self.load()["checks_passed"])
        self.assertFalse(self.load()["copilot_review_pending"])
        with self.assertRaisesRegex(SystemExit, "only once per PR"):
            self.run_cmd("record-copilot-request", head_sha="head-3", evidence="unwanted repeat")
        self.assertEqual(len(self.load()["copilot_review_requests"]), 1)

    def test_wait_expiry_and_stale_review_are_not_copilot_completion(self):
        self.review()
        self.publish()
        self.run_cmd("record-copilot-request", head_sha="head-1", evidence="request")
        after = datetime.fromisoformat(self.load()["copilot_review_started_at"]) + timedelta(seconds=600)
        with patch.object(cycle, "current_time", return_value=after):
            with self.assertRaisesRegex(SystemExit, "copilot-review"):
                self.run_cmd("mark-feedback-fetched", snapshot="no completed review")
            with self.assertRaisesRegex(SystemExit, "requested HEAD"):
                self.run_cmd("mark-feedback-fetched", snapshot="old review", copilot_review_head="old-head", copilot_review_evidence="old proof")
        self.assertIsNone(self.load()["remote_feedback_fetched_at"])

    def test_authorized_copilot_unavailability_does_not_fabricate_completion(self):
        self.review()
        self.publish()
        self.run_cmd("record-copilot-request", head_sha="head-1", evidence="request proof")
        evidence = Path(self.temp.name) / "denial.json"
        evidence.write_text(json.dumps({
            "pr_url": "https://github.com/example/repo/pull/1",
            "head_sha": "head-1",
            "request_attempted": True,
            "code_review_completed": False,
            "review_ids": [123],
            "reason": "Copilot quota exhausted",
        }))
        authorization = Path(self.temp.name) / "authorization.txt"
        authorization.write_text("User authorized a skip if Copilot cannot review this HEAD.")
        snapshot = Path(self.temp.name) / "feedback.json"
        snapshot.write_text("Raw fetched feedback")

        self.run_cmd(
            "record-copilot-unavailable",
            head_sha="head-1",
            evidence=evidence,
            authorization=authorization,
            snapshot=snapshot,
        )
        state = self.load()
        self.assertEqual(state["remote_feedback_snapshot"], str(snapshot.resolve()))
        self.assertEqual(state["copilot_unavailable"]["head_sha"], "head-1")
        self.assertEqual(state["copilot_unavailable"]["reason"], "Copilot quota exhausted")
        self.assertNotIn("copilot_review_completed", [event["kind"] for event in state["history"]])
        self.assertIn("copilot_review_unavailable", [event["kind"] for event in state["history"]])

        self.assess()
        self.run_cmd("record-checks", head_sha="head-1", result="pass", evidence="required checks passed")
        self.run_cmd("record-review-threads", head_sha="head-1", unresolved_count=0, evidence="fresh thread query")
        self.run_cmd("mark-merged", merge_sha="merge", evidence="merge proof")

    def test_copilot_unavailability_rejects_stale_head(self):
        self.review()
        self.publish()
        self.run_cmd("record-copilot-request", head_sha="head-1", evidence="request proof")
        evidence = Path(self.temp.name) / "denial.json"
        evidence.write_text(json.dumps({
            "pr_url": "https://github.com/example/repo/pull/1",
            "head_sha": "stale",
            "request_attempted": True,
            "code_review_completed": False,
            "review_ids": [123],
            "reason": "quota exhausted",
        }))
        authorization = Path(self.temp.name) / "authorization.txt"
        authorization.write_text("User authorized the conditional skip.")
        snapshot = Path(self.temp.name) / "feedback.json"
        snapshot.write_text("Raw fetched feedback")
        before = self.state.read_bytes()
        with self.assertRaisesRegex(SystemExit, "unavailable review.*HEAD"):
            self.run_cmd("record-copilot-unavailable", head_sha="head-1", evidence=evidence, authorization=authorization, snapshot=snapshot)
        self.assertEqual(self.state.read_bytes(), before)

    def test_strict_small_fix_does_not_fabricate_reviewer_pass(self):
        if not hasattr(cycle, "runtime_config"):
            self.skipTest("this adapter does not implement frozen strict routes")
        runtime = cycle.runtime_config
        config = runtime.load_config(SCRIPT.parent.parent / "config/runtimes/codex.json")
        routes = [r for r in config["roles"].values() if isinstance(r, dict)]
        routes.extend(config["roles"]["worker"]["tiers"].values())
        models = {}
        for route in routes:
            if route.get("model") and route.get("reasoning"):
                models.setdefault(route["model"], []).append(route["reasoning"])
        capabilities = dict(runtime="codex", max_children=4, fast_mode=False, persistent_worker=True, fresh_isolated_reviewers=True, evidence="local fixture host routes", models=models)
        snapshot = dict(snapshot_schema_version=1, status="ready", created_at=runtime.now_utc(), runtime="codex", policy_version=config["policy"]["id"], effective_config=config, sources={}, host_validation=runtime.validate_capabilities(config, capabilities))
        path = Path(self.temp.name) / "snapshot.json"
        path.write_text(json.dumps(snapshot))
        self.state = Path(self.temp.name) / "strict.json"
        manager = config["roles"]["manager"]
        self.run_cmd("init", issue="42", branch="codex/issue-42", manager_id="manager", mode="quick", runtime_snapshot=path, manager_profile=manager["role"], manager_model=manager["model"], manager_reasoning=manager["reasoning"])
        self.run_cmd("record-assessment", affected_modules="gate", coupling_and_difficulty="localized gate", unresolved_decisions="none", tier="simple", validation_plan="negative gate fixture")
        worker = config["roles"]["worker"]["tiers"]["simple"]
        self.worker = dict(worker_id="worker", worker_profile=worker["role"], worker_provider="openai", worker_model=worker["model"], worker_reasoning=worker["reasoning"])
        self.run_cmd("record-worker", **self.worker, tier="simple", continuity="worker_identity_profile")
        self.run_cmd("start-implementation", **self.worker)
        reviewer = config["roles"]["reviewer"]
        self.run_cmd("start-review", reviewer_id="fresh-reviewer", reviewer_profile=reviewer["role"], reviewer_provider="openai", reviewer_model=reviewer["model"], reviewer_reasoning=reviewer["reasoning"])
        if config["roles"]["judge"].get("provider") == "typesafe-ai":
            report = Path(self.temp.name) / "strict-typesafe.json"
            report.write_text(json.dumps(dict(schema_version=1, question_set="issue-to-merge-typesafe-review-v1", requested_model="jev-latest", review_kind="local")))
            self.run_cmd("record-typesafe-review", report=report)
        self.run_cmd("finish-review", outcome="changes", report="review.md", summary="one reproducible finding")
        self.fix()
        self.publish()
        self.assertIsNone(self.load()["last_local_pass"])
        self.assertEqual(self.load()["last_review_outcome"], "changes")


if __name__ == "__main__":
    unittest.main()
