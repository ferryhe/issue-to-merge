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

        self.assertIn("same-shaped sibling sites to inspect", worker_fields)
        self.assertIn("expected pre-fix failure and post-fix pass evidence", worker_fields)
        self.assertIn("feature-only work is exempt", worker_fields)
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


if __name__ == "__main__":
    unittest.main()
