#!/usr/bin/env python3
"""Persist and enforce one managed Issue's review and PR lifecycle."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NoReturn


MAX_REVIEWS = 15
REMOTE_WAIT_SECONDS = 600
SCHEMA_VERSION = 3


def current_time() -> datetime:
    return datetime.now(timezone.utc)


def now_utc() -> str:
    return current_time().isoformat()


def fail(message: str) -> NoReturn:
    raise SystemExit(f"error: {message}")


def require_text(value: str | None, name: str) -> str:
    if value is None or not value.strip():
        fail(f"{name} must be nonempty")
    return value.strip()


def load_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        fail(f"state file does not exist: {path}")
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read state file {path}: {exc}")
    if state.get("schema_version") != SCHEMA_VERSION:
        fail("unsupported or missing schema_version")
    max_reviews = state.get("max_reviews")
    if not isinstance(max_reviews, int) or max_reviews < 1 or max_reviews > MAX_REVIEWS:
        fail(f"state max_reviews must be an integer from 1 to {MAX_REVIEWS}")
    return state


def review_limit(state: dict[str, Any]) -> int:
    return int(state.get("max_reviews", MAX_REVIEWS))


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = now_utc()
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def add_event(state: dict[str, Any], kind: str, **details: Any) -> None:
    state["history"].append({"at": now_utc(), "kind": kind, **details})


def state_path(args: argparse.Namespace) -> Path:
    return Path(args.state_file).resolve()


def decisions_log_path(args: argparse.Namespace) -> Path:
    path = state_path(args)
    return path.with_name(path.name + ".decisions.log")


def append_decision(log_path: Path, point: str, outcome: str, reason: str) -> None:
    record = {"at": now_utc(), "point": point, "outcome": outcome, "reason": reason}
    with log_path.open("a", encoding="utf-8", newline="\n") as handle:
        json.dump(record, handle, ensure_ascii=False, sort_keys=True)
        handle.write("\n")


def cmd_init(args: argparse.Namespace) -> dict[str, Any]:
    path = state_path(args)
    if path.exists():
        fail(f"refusing to overwrite existing state file: {path}")
    issue = require_text(args.issue, "issue")
    branch = require_text(args.branch, "branch")
    manager_id = require_text(args.manager_id, "manager-id")
    created = now_utc()
    state: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "issue": issue.removeprefix("#"),
        "branch": branch,
        "manager_id": manager_id,
        "created_at": created,
        "updated_at": created,
        "max_reviews": MAX_REVIEWS,
        "review_count": 0,
        "active_review": False,
        "active_review_number": None,
        "needs_fix": False,
        "local_review_closed": False,
        "final_unreviewed_fix": False,
        "stage": "implementing",
        "pr_url": None,
        "pr_head_sha": None,
        "closing_reference": None,
        "remote_feedback_started_at": None,
        "remote_feedback_fetched_at": None,
        "remote_feedback_snapshot": None,
        "remote_assessment": None,
        "blocked_resolution": None,
        "remote_fix_completed_at": None,
        "remote_fix_count": 0,
        "remote_fixes": [],
        "checks_passed": False,
        "checks_evidence": None,
        "merged_at": None,
        "merge_sha": None,
        "issue_closed_verified_at": None,
        "cleanup": {
            "remote_branch": None,
            "worktree": None,
            "local_branch": None,
            "base_branch": None,
        },
        "task_close": None,
        "history": [],
    }
    add_event(state, "initialized")
    save_state(path, state)
    return state


def cmd_start_review(args: argparse.Namespace) -> dict[str, Any]:
    path = state_path(args)
    state = load_state(path)
    if state["local_review_closed"]:
        fail("local review is already closed")
    if state["active_review"]:
        fail("a review is already active")
    if state["needs_fix"]:
        fail("record the required worker fix before starting another review")
    max_reviews = review_limit(state)
    if state["review_count"] >= max_reviews:
        fail("review limit reached; another completed review is forbidden")
    round_number = state["review_count"] + 1
    state["active_review"] = True
    state["active_review_number"] = round_number
    state["stage"] = "local_review"
    add_event(state, "review_started", round=round_number)
    save_state(path, state)
    return state


def cmd_abort_review(args: argparse.Namespace) -> dict[str, Any]:
    path = state_path(args)
    state = load_state(path)
    if not state["active_review"]:
        fail("no active review to abort")
    reason = require_text(args.reason, "reason")
    round_number = state["active_review_number"]
    state["active_review"] = False
    state["active_review_number"] = None
    state["stage"] = "awaiting_review"
    add_event(state, "review_aborted", attempted_round=round_number, reason=reason)
    save_state(path, state)
    return state


def cmd_finish_review(args: argparse.Namespace) -> dict[str, Any]:
    path = state_path(args)
    state = load_state(path)
    if not state["active_review"]:
        fail("no active review to finish")
    report = require_text(args.report, "report")
    summary = require_text(args.summary, "summary")
    round_number = state["active_review_number"]
    if round_number != state["review_count"] + 1 or round_number > review_limit(state):
        fail("active review number is inconsistent with the completed count")
    state["review_count"] = round_number
    state["active_review"] = False
    state["active_review_number"] = None
    state["last_review_outcome"] = args.outcome
    if args.outcome == "pass":
        state["needs_fix"] = False
        state["local_review_closed"] = True
        state["stage"] = "local_review_complete"
    else:
        state["needs_fix"] = True
        state["stage"] = "fixing"
    add_event(state, "review_finished", round=round_number, outcome=args.outcome, report=report, summary=summary)
    save_state(path, state)
    return state


def cmd_record_fix(args: argparse.Namespace) -> dict[str, Any]:
    path = state_path(args)
    state = load_state(path)
    if state["active_review"]:
        fail("finish the active review before recording a fix")
    if not state["needs_fix"]:
        fail("no reviewer-requested fix is pending")
    report = require_text(args.report, "report")
    validation = require_text(args.validation, "validation")
    state["needs_fix"] = False
    final_fix = state["review_count"] == review_limit(state)
    if final_fix:
        state["local_review_closed"] = True
        state["final_unreviewed_fix"] = True
        state["stage"] = "local_review_complete"
    else:
        state["stage"] = "awaiting_review"
    add_event(state, "fix_recorded", after_round=state["review_count"], final_unreviewed_fix=final_fix, report=report, validation=validation)
    save_state(path, state)
    return state


def cmd_record_pr(args: argparse.Namespace) -> dict[str, Any]:
    path = state_path(args)
    state = load_state(path)
    if not state["local_review_closed"] or state["active_review"] or state["needs_fix"]:
        fail("local review must be closed with no active review or pending fix")
    if state["pr_url"] is not None:
        fail("PR is already recorded")
    url = require_text(args.url, "url")
    head_sha = require_text(args.head_sha, "head-sha")
    closing_reference = require_text(args.closing_reference, "closing-reference")
    expected = f"closes #{state['issue']}"
    if closing_reference.casefold() != expected.casefold():
        fail(f"closing-reference must be exactly: Closes #{state['issue']}")
    state["pr_url"] = url
    state["pr_head_sha"] = head_sha
    state["closing_reference"] = closing_reference
    state["checks_passed"] = False
    state["checks_evidence"] = None
    state["stage"] = "pr_draft"
    add_event(state, "pr_recorded", url=url, head_sha=head_sha, closing_reference=closing_reference)
    save_state(path, state)
    return state


def cmd_mark_ready(args: argparse.Namespace) -> dict[str, Any]:
    path = state_path(args)
    state = load_state(path)
    if state["stage"] != "pr_draft" or state["pr_url"] is None:
        fail("a recorded Draft PR is required before Ready for review")
    if state["remote_feedback_started_at"] is not None:
        fail("Ready timestamp is already recorded and cannot be reset")
    state["remote_feedback_started_at"] = now_utc()
    state["stage"] = "pr_ready"
    add_event(state, "pr_marked_ready", head_sha=state["pr_head_sha"])
    save_state(path, state)
    return state


def cmd_mark_feedback_fetched(args: argparse.Namespace) -> dict[str, Any]:
    path = state_path(args)
    state = load_state(path)
    snapshot = require_text(args.snapshot, "snapshot")
    started_raw = state["remote_feedback_started_at"]
    if started_raw is None:
        fail("PR Ready timestamp is missing")
    if state["remote_feedback_fetched_at"] is not None:
        fail("remote feedback was already fetched; a second fetch is forbidden")
    started = datetime.fromisoformat(started_raw)
    elapsed = (current_time() - started).total_seconds()
    if elapsed < REMOTE_WAIT_SECONDS:
        fail(f"remote feedback window has {REMOTE_WAIT_SECONDS - elapsed:.1f} seconds remaining")
    state["remote_feedback_fetched_at"] = now_utc()
    state["remote_feedback_snapshot"] = snapshot
    state["stage"] = "remote_feedback_fetched"
    add_event(state, "remote_feedback_fetched", snapshot=snapshot, elapsed_seconds=elapsed)
    save_state(path, state)
    return state


def cmd_record_remote_assessment(args: argparse.Namespace) -> dict[str, Any]:
    path = state_path(args)
    state = load_state(path)
    if state["remote_feedback_fetched_at"] is None:
        fail("record the one allowed remote feedback fetch first")
    if state["remote_assessment"] is not None:
        fail("remote feedback assessment is already recorded")
    report = require_text(args.report, "report")
    state["remote_assessment"] = {"outcome": args.outcome, "report": report, "at": now_utc()}
    if args.outcome == "clean":
        state["stage"] = "merge_ready"
    elif args.outcome == "changes":
        state["stage"] = "remote_fix"
    else:
        state["stage"] = "blocked"
    add_event(state, "remote_assessment_recorded", outcome=args.outcome, report=report)
    save_state(path, state)
    return state


def cmd_resolve_blocked(args: argparse.Namespace) -> dict[str, Any]:
    path = state_path(args)
    state = load_state(path)
    if not state["remote_assessment"] or state["remote_assessment"]["outcome"] != "blocked":
        fail("a blocked remote assessment is required")
    if state["stage"] != "blocked" or state["blocked_resolution"] is not None:
        fail("blocked feedback is already resolved or state is inconsistent")
    evidence = require_text(args.evidence, "evidence")
    state["blocked_resolution"] = {"decision": args.decision, "evidence": evidence, "at": now_utc()}
    state["stage"] = "merge_ready" if args.decision == "merge" else "remote_fix"
    add_event(state, "blocked_feedback_resolved", decision=args.decision, evidence=evidence)
    save_state(path, state)
    return state


def cmd_record_remote_fix(args: argparse.Namespace) -> dict[str, Any]:
    path = state_path(args)
    state = load_state(path)
    assessment_requires_changes = bool(state["remote_assessment"] and state["remote_assessment"]["outcome"] == "changes")
    resolution_requires_changes = bool(state["blocked_resolution"] and state["blocked_resolution"]["decision"] == "changes")
    if not assessment_requires_changes and not resolution_requires_changes:
        fail("remote assessment or blocked resolution must require changes")
    if state["stage"] not in {"remote_fix", "merge_ready"}:
        fail("remote fix is not allowed in the current lifecycle stage")
    if state["remote_fix_count"] > 0:
        checks = state["checks_evidence"]
        if not checks or checks["result"] != "fail" or checks["head_sha"] != state["pr_head_sha"]:
            fail("another remote repair is allowed only after failed checks on the current PR HEAD")
    head_sha = require_text(args.head_sha, "head-sha")
    validation = require_text(args.validation, "validation")
    if head_sha == state["pr_head_sha"]:
        fail("remote fix must record a new PR HEAD SHA")
    repair_number = state["remote_fix_count"] + 1
    state["pr_head_sha"] = head_sha
    state["checks_passed"] = False
    state["checks_evidence"] = None
    state["remote_fix_completed_at"] = now_utc()
    state["remote_fix_count"] = repair_number
    state["remote_fixes"].append({"number": repair_number, "head_sha": head_sha, "validation": validation, "at": state["remote_fix_completed_at"]})
    state["stage"] = "merge_ready"
    add_event(state, "remote_fix_recorded", number=repair_number, head_sha=head_sha, validation=validation)
    save_state(path, state)
    return state


def cmd_record_checks(args: argparse.Namespace) -> dict[str, Any]:
    path = state_path(args)
    state = load_state(path)
    if state["pr_url"] is None:
        fail("record the PR before its checks")
    head_sha = require_text(args.head_sha, "head-sha")
    evidence = require_text(args.evidence, "evidence")
    if head_sha != state["pr_head_sha"]:
        fail("checks must refer to the current PR HEAD SHA")
    state["checks_passed"] = args.result == "pass"
    state["checks_evidence"] = {"head_sha": head_sha, "result": args.result, "evidence": evidence, "at": now_utc()}
    add_event(state, "checks_recorded", head_sha=head_sha, result=args.result, evidence=evidence)
    save_state(path, state)
    return state


def cmd_mark_merged(args: argparse.Namespace) -> dict[str, Any]:
    path = state_path(args)
    state = load_state(path)
    if state["stage"] != "merge_ready" or state["remote_assessment"] is None:
        fail("completed remote assessment is required before merge")
    if not state["checks_passed"]:
        fail("current PR HEAD must have passing required checks")
    merge_sha = require_text(args.merge_sha, "merge-sha")
    evidence = require_text(args.evidence, "evidence")
    state["merged_at"] = now_utc()
    state["merge_sha"] = merge_sha
    state["stage"] = "merged"
    add_event(state, "merged", merge_sha=merge_sha, evidence=evidence)
    save_state(path, state)
    return state


def cmd_verify_issue_closed(args: argparse.Namespace) -> dict[str, Any]:
    path = state_path(args)
    state = load_state(path)
    if state["stage"] != "merged" or state["merged_at"] is None:
        fail("record the merge before verifying Issue closure")
    if state["issue_closed_verified_at"] is not None:
        fail("Issue closure is already verified")
    evidence = require_text(args.evidence, "evidence")
    state["issue_closed_verified_at"] = now_utc()
    add_event(state, "issue_closed_verified", evidence=evidence)
    save_state(path, state)
    return state


def record_cleanup_step(args: argparse.Namespace, step: str, required_previous: str | None) -> dict[str, Any]:
    path = state_path(args)
    state = load_state(path)
    if state["issue_closed_verified_at"] is None:
        fail("verify the Issue is closed before cleanup")
    if required_previous and state["cleanup"][required_previous] is None:
        fail(f"cleanup step {required_previous} must be recorded first")
    if state["cleanup"][step] is not None:
        fail(f"cleanup step {step} is already recorded")
    evidence = require_text(args.evidence, "evidence")
    state["cleanup"][step] = {"at": now_utc(), "evidence": evidence}
    state["stage"] = f"cleanup_{step}"
    add_event(state, f"cleanup_{step}_recorded", evidence=evidence)
    save_state(path, state)
    return state


def cmd_record_remote_branch(args: argparse.Namespace) -> dict[str, Any]:
    return record_cleanup_step(args, "remote_branch", None)


def cmd_record_worktree(args: argparse.Namespace) -> dict[str, Any]:
    return record_cleanup_step(args, "worktree", "remote_branch")


def cmd_record_local_branch(args: argparse.Namespace) -> dict[str, Any]:
    return record_cleanup_step(args, "local_branch", "worktree")


def cmd_mark_cleaned(args: argparse.Namespace) -> dict[str, Any]:
    path = state_path(args)
    state = load_state(path)
    if state["cleanup"]["local_branch"] is None:
        fail("remote branch, worktree, and local branch cleanup must be recorded in order")
    if state["cleanup"]["base_branch"] is not None:
        fail("default-branch refresh is already recorded")
    evidence = require_text(args.base_branch_evidence, "base-branch-evidence")
    state["cleanup"]["base_branch"] = {"at": now_utc(), "evidence": evidence}
    state["stage"] = "cleaned"
    add_event(state, "cleaned", base_branch_evidence=evidence)
    save_state(path, state)
    return state


def cmd_mark_task_closed(args: argparse.Namespace) -> dict[str, Any]:
    path = state_path(args)
    state = load_state(path)
    if state.get("task_close") is not None:
        fail("Issue task closure is already recorded")
    if state["stage"] != "cleaned" or state["cleanup"]["base_branch"] is None:
        fail("complete cleanup before recording task closure")
    evidence = require_text(args.evidence, "evidence")
    state["task_close"] = {"at": now_utc(), "evidence": evidence}
    state["stage"] = "task_closed"
    add_event(state, "task_closed", evidence=evidence)
    save_state(path, state)
    return state


def cmd_status(args: argparse.Namespace) -> dict[str, Any]:
    return load_state(state_path(args))


def cmd_record_decision(args: argparse.Namespace) -> dict[str, Any]:
    path = state_path(args)
    state = load_state(path)
    point = require_text(args.point, "point")
    outcome = require_text(args.outcome, "outcome")
    reason = require_text(args.reason, "reason")
    append_decision(decisions_log_path(args), point, outcome, reason)
    add_event(state, "decision_recorded", point=point, outcome=outcome, reason=reason)
    save_state(path, state)
    return state


def cmd_show_decisions(args: argparse.Namespace) -> None:
    log_path = decisions_log_path(args)
    if not log_path.is_file():
        print("(no decisions recorded)")
    else:
        sys.stdout.write(log_path.read_text(encoding="utf-8"))
    return None


def add_state_file(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--state-file", required=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", help="create state for one Issue")
    add_state_file(init)
    init.add_argument("--issue", required=True)
    init.add_argument("--branch", required=True)
    init.add_argument("--manager-id", required=True)
    init.set_defaults(handler=cmd_init)

    start = commands.add_parser("start-review", help="reserve the next reviewer round")
    add_state_file(start)
    start.set_defaults(handler=cmd_start_review)

    abort = commands.add_parser("abort-review", help="abort a reviewer attempt without consuming a round")
    add_state_file(abort)
    abort.add_argument("--reason", required=True)
    abort.set_defaults(handler=cmd_abort_review)

    finish = commands.add_parser("finish-review", help="record a completed reviewer verdict")
    add_state_file(finish)
    finish.add_argument("--outcome", choices=("pass", "changes"), required=True)
    finish.add_argument("--report", required=True)
    finish.add_argument("--summary", required=True)
    finish.set_defaults(handler=cmd_finish_review)

    fix = commands.add_parser("record-fix", help="record the worker fix after findings")
    add_state_file(fix)
    fix.add_argument("--report", required=True)
    fix.add_argument("--validation", required=True)
    fix.set_defaults(handler=cmd_record_fix)

    pr = commands.add_parser("record-pr", help="record the Draft PR and Issue-closing reference")
    add_state_file(pr)
    pr.add_argument("--url", required=True)
    pr.add_argument("--head-sha", required=True)
    pr.add_argument("--closing-reference", required=True)
    pr.set_defaults(handler=cmd_record_pr)

    ready = commands.add_parser("mark-ready", help="record Ready time exactly once")
    add_state_file(ready)
    ready.set_defaults(handler=cmd_mark_ready)

    fetched = commands.add_parser("mark-feedback-fetched", help="record the single remote fetch after 600 seconds")
    add_state_file(fetched)
    fetched.add_argument("--snapshot", required=True)
    fetched.set_defaults(handler=cmd_mark_feedback_fetched)

    assessment = commands.add_parser("record-remote-assessment", help="record the one remote-feedback assessment")
    add_state_file(assessment)
    assessment.add_argument("--outcome", choices=("clean", "changes", "blocked"), required=True)
    assessment.add_argument("--report", required=True)
    assessment.set_defaults(handler=cmd_record_remote_assessment)

    resolution = commands.add_parser("resolve-blocked", help="record an explicit decision for blocked remote feedback")
    add_state_file(resolution)
    resolution.add_argument("--decision", choices=("merge", "changes"), required=True)
    resolution.add_argument("--evidence", required=True)
    resolution.set_defaults(handler=cmd_resolve_blocked)

    remote_fix = commands.add_parser("record-remote-fix", help="record manager-validated remote changes")
    add_state_file(remote_fix)
    remote_fix.add_argument("--head-sha", required=True)
    remote_fix.add_argument("--validation", required=True)
    remote_fix.set_defaults(handler=cmd_record_remote_fix)

    checks = commands.add_parser("record-checks", help="record required checks for current PR HEAD")
    add_state_file(checks)
    checks.add_argument("--head-sha", required=True)
    checks.add_argument("--result", choices=("pass", "fail"), required=True)
    checks.add_argument("--evidence", required=True)
    checks.set_defaults(handler=cmd_record_checks)

    merged = commands.add_parser("mark-merged", help="record a permitted merge")
    add_state_file(merged)
    merged.add_argument("--merge-sha", required=True)
    merged.add_argument("--evidence", required=True)
    merged.set_defaults(handler=cmd_mark_merged)

    issue_closed = commands.add_parser("verify-issue-closed", help="record independent Issue closure proof")
    add_state_file(issue_closed)
    issue_closed.add_argument("--evidence", required=True)
    issue_closed.set_defaults(handler=cmd_verify_issue_closed)

    remote_branch = commands.add_parser("record-remote-branch-cleaned", help="record remote branch deletion")
    add_state_file(remote_branch)
    remote_branch.add_argument("--evidence", required=True)
    remote_branch.set_defaults(handler=cmd_record_remote_branch)

    worktree = commands.add_parser("record-worktree-removed", help="record worktree removal after remote branch deletion")
    add_state_file(worktree)
    worktree.add_argument("--evidence", required=True)
    worktree.set_defaults(handler=cmd_record_worktree)

    local_branch = commands.add_parser("record-local-branch-deleted", help="record local branch deletion after worktree removal")
    add_state_file(local_branch)
    local_branch.add_argument("--evidence", required=True)
    local_branch.set_defaults(handler=cmd_record_local_branch)

    cleaned = commands.add_parser("mark-cleaned", help="record the refreshed default branch and finish cleanup")
    add_state_file(cleaned)
    cleaned.add_argument("--base-branch-evidence", required=True)
    cleaned.set_defaults(handler=cmd_mark_cleaned)

    task_closed = commands.add_parser("mark-task-closed", help="record Issue task closure after cleanup")
    add_state_file(task_closed)
    task_closed.add_argument("--evidence", required=True)
    task_closed.set_defaults(handler=cmd_mark_task_closed)

    record_decision = commands.add_parser("record-decision", help="append one decision to the append-only decisions log")
    add_state_file(record_decision)
    record_decision.add_argument("--point", required=True)
    record_decision.add_argument("--outcome", required=True)
    record_decision.add_argument("--reason", required=True)
    record_decision.set_defaults(handler=cmd_record_decision)

    show_decisions = commands.add_parser("show-decisions", help="print the append-only decisions log")
    add_state_file(show_decisions)
    show_decisions.set_defaults(handler=cmd_show_decisions)

    status = commands.add_parser("status", help="print current state")
    add_state_file(status)
    status.set_defaults(handler=cmd_status)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = args.handler(args)
    if result is not None:
        json.dump(result, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
