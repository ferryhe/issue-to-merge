#!/usr/bin/env python3
"""Persist and enforce one managed Issue's review and PR lifecycle."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NoReturn

try:
    import runtime_config
except ModuleNotFoundError:
    _runtime_spec = importlib.util.spec_from_file_location(
        "runtime_config", Path(__file__).with_name("runtime_config.py")
    )
    if _runtime_spec is None or _runtime_spec.loader is None:
        raise
    runtime_config = importlib.util.module_from_spec(_runtime_spec)
    _runtime_spec.loader.exec_module(runtime_config)


MAX_REVIEWS = 15
REMOTE_WAIT_SECONDS = 600
SCHEMA_VERSION = 3
SUPPORTED_WORKER_CONTINUITY = "worker_identity_profile"


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


def normalize_state(state: dict[str, Any]) -> dict[str, Any]:
    had_implementation_started_at = "implementation_started_at" in state
    had_legacy_in_progress = "legacy_in_progress" in state
    worker = state.get("worker")
    if isinstance(worker, dict):
        worker.setdefault("provider", None)
        worker.setdefault("model", None)
        worker.setdefault("reasoning", None)
    state.setdefault("worker", None)
    state.setdefault("worker_continuity", SUPPORTED_WORKER_CONTINUITY)
    state.setdefault("active_reviewer", None)
    state.setdefault("used_reviewer_ids", [])
    state.setdefault("check_repair_count", 0)
    state.setdefault("check_repairs", [])
    state.setdefault("review_threads_evidence", None)
    state.setdefault("implementation_started_at", None)
    state.setdefault("legacy_in_progress", False)
    state.setdefault("runtime_snapshot", None)
    state.setdefault("runtime_snapshot_hash", None)
    state.setdefault("assessment", None)
    state.setdefault("failed_review_cycles", 0)
    state.setdefault("pending_adjudication", None)
    state.setdefault("adjudications", [])
    state.setdefault("used_judge_ids", [])
    state.setdefault("last_local_pass", None)
    if not had_implementation_started_at or not had_legacy_in_progress:
        if is_legacy_in_progress_state(state):
            state["legacy_in_progress"] = True
    return state


def is_legacy_in_progress_state(state: dict[str, Any]) -> bool:
    return bool(
        state.get("worker")
        and (
            state.get("review_count", 0) > 0
            or state.get("active_review")
            or state.get("needs_fix")
            or state.get("local_review_closed")
            or state.get("pr_url") is not None
            or state.get("remote_feedback_started_at") is not None
            or state.get("remote_feedback_fetched_at") is not None
            or state.get("remote_assessment") is not None
            or state.get("blocked_resolution") is not None
            or state.get("remote_fix_count", 0) > 0
            or state.get("checks_evidence") is not None
            or state.get("merged_at") is not None
            or state.get("issue_closed_verified_at") is not None
            or any(value is not None for value in state.get("cleanup", {}).values())
            or state.get("task_close") is not None
        )
    )


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
    state = normalize_state(state)
    snapshot = state.get("runtime_snapshot")
    if snapshot is not None:
        try:
            runtime_config.validate_snapshot(snapshot)
        except runtime_config.ConfigError as exc:
            fail(f"invalid frozen runtime snapshot in state: {exc}")
        expected_hash = state.get("runtime_snapshot_hash")
        if expected_hash != snapshot_hash(snapshot):
            fail("frozen runtime snapshot in state was modified")
    if state["worker_continuity"] != SUPPORTED_WORKER_CONTINUITY:
        fail("unsupported worker continuity contract in state file")
    if not isinstance(state["used_reviewer_ids"], list):
        fail("state used_reviewer_ids must be a list")
    if not isinstance(state["used_judge_ids"], list):
        fail("state used_judge_ids must be a list")
    return state


def review_limit(state: dict[str, Any]) -> int:
    return int(state.get("max_reviews", MAX_REVIEWS))


def snapshot_hash(snapshot: dict[str, Any]) -> str:
    encoded = json.dumps(
        snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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


def require_worker_continuity(value: str | None) -> str:
    continuity = require_text(value, "continuity")
    if continuity == "exact_session":
        fail("exact-session continuity is unsupported; use worker_identity_profile")
    if continuity != SUPPORTED_WORKER_CONTINUITY:
        fail(f"unsupported worker continuity contract: {continuity}")
    return continuity


def require_worker_recorded(state: dict[str, Any], *, action: str) -> dict[str, Any]:
    worker = state.get("worker")
    if not worker:
        fail(f"record the implementation worker before {action}")
    if worker.get("provider") is None or worker.get("model") is None:
        fail("enrich the recorded worker with provider and model first")
    return worker


def require_implementation_started(state: dict[str, Any], *, action: str) -> None:
    if state.get("implementation_started_at") is not None:
        return
    if state.get("legacy_in_progress"):
        return
    fail(f"start implementation before {action}")


def require_worker_match(state: dict[str, Any], args: argparse.Namespace) -> dict[str, str]:
    worker = require_worker_recorded(state, action="worker-driven lifecycle transitions")
    worker_id = require_text(getattr(args, "worker_id", None), "worker-id")
    worker_profile = require_text(getattr(args, "worker_profile", None), "worker-profile")
    if worker["id"] != worker_id or worker["profile"] != worker_profile:
        fail("worker identity/profile does not match the recorded implementation worker")
    worker_provider = require_text(getattr(args, "worker_provider", None), "worker-provider")
    worker_model = require_text(getattr(args, "worker_model", None), "worker-model")
    if worker["provider"] != worker_provider or worker["model"] != worker_model:
        fail("worker provider/model does not match the recorded implementation worker")
    worker_reasoning = getattr(args, "worker_reasoning", None)
    if is_strict_state(state):
        worker_reasoning = require_text(worker_reasoning, "worker-reasoning")
    if worker.get("reasoning") != worker_reasoning:
        fail("worker reasoning does not match the recorded implementation worker")
    return worker


def is_strict_state(state: dict[str, Any]) -> bool:
    snapshot = state.get("runtime_snapshot")
    return bool(
        isinstance(snapshot, dict)
        and snapshot.get("effective_config", {}).get("policy", {}).get("strict_lifecycle")
    )


def strict_config(state: dict[str, Any]) -> dict[str, Any]:
    if not is_strict_state(state):
        fail("this transition requires a selected strict runtime policy")
    return state["runtime_snapshot"]["effective_config"]


def require_no_pending_adjudication(state: dict[str, Any], *, action: str) -> None:
    pending = state.get("pending_adjudication")
    if pending:
        fail(
            f"resolve pending adjudication {pending['evidence_key']!r} before {action}"
        )


def load_runtime_snapshot(path_value: str | None) -> dict[str, Any] | None:
    if path_value is None:
        return None
    path = Path(path_value).resolve()
    try:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read runtime snapshot {path}: {exc}")
    if not isinstance(snapshot, dict):
        fail("runtime snapshot root must be an object")
    try:
        runtime_config.validate_snapshot(snapshot)
    except runtime_config.ConfigError as exc:
        fail(f"invalid runtime snapshot: {exc}")
    return snapshot


def require_route(
    actual_profile: str,
    actual_model: str,
    actual_reasoning: str,
    expected: dict[str, Any],
    role_name: str,
) -> None:
    if actual_profile != expected.get("role"):
        fail(f"{role_name} profile/role must be {expected.get('role')!r}")
    if actual_model != expected.get("model") or actual_reasoning != expected.get("reasoning"):
        fail(
            f"{role_name} route must be "
            f"{expected.get('model')}/{expected.get('reasoning')}"
        )


def add_worker_identity_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--worker-id", required=True)
    parser.add_argument("--worker-profile", required=True)
    parser.add_argument("--worker-provider", required=True)
    parser.add_argument("--worker-model", required=True)
    parser.add_argument("--worker-reasoning")


def cmd_init(args: argparse.Namespace) -> dict[str, Any]:
    path = state_path(args)
    if path.exists():
        fail(f"refusing to overwrite existing state file: {path}")
    issue = require_text(args.issue, "issue")
    branch = require_text(args.branch, "branch")
    manager_id = require_text(args.manager_id, "manager-id")
    runtime_snapshot = load_runtime_snapshot(getattr(args, "runtime_snapshot", None))
    if runtime_snapshot and runtime_snapshot["effective_config"]["policy"]["strict_lifecycle"]:
        expected_manager = runtime_snapshot["effective_config"]["roles"]["manager"]
        manager_profile = require_text(getattr(args, "manager_profile", None), "manager-profile")
        manager_model = require_text(getattr(args, "manager_model", None), "manager-model")
        manager_reasoning = require_text(
            getattr(args, "manager_reasoning", None), "manager-reasoning"
        )
        require_route(
            manager_profile,
            manager_model,
            manager_reasoning,
            expected_manager,
            "manager",
        )
    created = now_utc()
    state: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "issue": issue.removeprefix("#"),
        "branch": branch,
        "manager_id": manager_id,
        "created_at": created,
        "updated_at": created,
        "max_reviews": (
            runtime_snapshot["effective_config"]["policy"]["review_limit"]
            if runtime_snapshot
            else MAX_REVIEWS
        ),
        "review_count": 0,
        "active_review": False,
        "active_review_number": None,
        "needs_fix": False,
        "local_review_closed": False,
        "final_unreviewed_fix": False,
        "stage": "assessment" if runtime_snapshot and runtime_snapshot["effective_config"]["policy"]["assessment_required"] else "worker_selection",
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
        "review_threads_evidence": None,
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
        "worker": None,
        "worker_continuity": SUPPORTED_WORKER_CONTINUITY,
        "active_reviewer": None,
        "used_reviewer_ids": [],
        "check_repair_count": 0,
        "check_repairs": [],
        "implementation_started_at": None,
        "legacy_in_progress": False,
        "runtime_snapshot": runtime_snapshot,
        "runtime_snapshot_hash": snapshot_hash(runtime_snapshot) if runtime_snapshot else None,
        "assessment": None,
        "failed_review_cycles": 0,
        "pending_adjudication": None,
        "adjudications": [],
        "used_judge_ids": [],
        "last_local_pass": None,
    }
    add_event(
        state,
        "initialized",
        runtime=runtime_snapshot["runtime"] if runtime_snapshot else None,
        policy_version=runtime_snapshot["policy_version"] if runtime_snapshot else None,
    )
    save_state(path, state)
    return state


def cmd_record_assessment(args: argparse.Namespace) -> dict[str, Any]:
    path = state_path(args)
    state = load_state(path)
    config = strict_config(state)
    if state["assessment"] is not None:
        fail("implementation assessment is already recorded")
    if state["stage"] != "assessment" or state["worker"] is not None:
        fail("assessment must be recorded before worker selection")
    tier = require_text(args.tier, "tier")
    tiers = config["roles"]["worker"]["tiers"]
    if tier not in tiers:
        fail(f"assessment tier is unavailable in selected runtime: {tier}")
    assessment = {
        "affected_modules": require_text(args.affected_modules, "affected-modules"),
        "coupling_and_difficulty": require_text(
            args.coupling_and_difficulty, "coupling-and-difficulty"
        ),
        "unresolved_decisions": require_text(
            args.unresolved_decisions, "unresolved-decisions"
        ),
        "tier": tier,
        "validation_plan": require_text(args.validation_plan, "validation-plan"),
        "recorded_at": now_utc(),
    }
    state["assessment"] = assessment
    state["stage"] = "worker_selection"
    if args.uncertainty_evidence_key is not None:
        evidence_key = require_text(
            args.uncertainty_evidence_key, "uncertainty-evidence-key"
        )
        evidence = require_text(args.uncertainty_evidence, "uncertainty-evidence")
        state["pending_adjudication"] = {
            "trigger": "architecture_security_uncertainty",
            "evidence_key": evidence_key,
            "evidence": evidence,
            "revision": None,
            "report": None,
            "requested_at": now_utc(),
            "outcome": "pending",
            "resume_stage": "worker_selection",
        }
        state["stage"] = "adjudication"
        add_event(
            state,
            "adjudication_requested",
            trigger="architecture_security_uncertainty",
            evidence_key=evidence_key,
            revision=None,
            report=None,
        )
    elif args.uncertainty_evidence is not None:
        fail("uncertainty-evidence-key is required with uncertainty-evidence")
    add_event(state, "assessment_recorded", **assessment)
    save_state(path, state)
    return state


def cmd_request_judge(args: argparse.Namespace) -> dict[str, Any]:
    path = state_path(args)
    state = load_state(path)
    config = strict_config(state)
    if state["pending_adjudication"] is not None:
        fail("an adjudication is already pending")
    trigger = args.trigger
    judge_policy = config["policy"]["judge"]
    if trigger == "reviewer_disagreement" and not judge_policy["reviewer_disagreement"]:
        fail("selected policy does not route reviewer disagreement to Judge")
    if (
        trigger == "architecture_security_uncertainty"
        and not judge_policy["architecture_security_uncertainty"]
    ):
        fail("selected policy does not route architecture/security uncertainty to Judge")
    evidence_key = require_text(args.evidence_key, "evidence-key")
    if any(item["evidence_key"] == evidence_key for item in state["adjudications"]):
        fail("adjudication evidence key was already resolved")
    resume_stage = state["stage"]
    state["pending_adjudication"] = {
        "trigger": trigger,
        "evidence_key": evidence_key,
        "evidence": require_text(args.evidence, "evidence"),
        "revision": require_text(args.revision, "revision"),
        "report": require_text(args.report, "report"),
        "requested_at": now_utc(),
        "outcome": "pending",
        "resume_stage": resume_stage,
    }
    state["stage"] = "adjudication"
    add_event(
        state,
        "adjudication_requested",
        trigger=trigger,
        evidence_key=evidence_key,
        revision=state["pending_adjudication"]["revision"],
        report=state["pending_adjudication"]["report"],
    )
    save_state(path, state)
    return state


def cmd_record_judge(args: argparse.Namespace) -> dict[str, Any]:
    path = state_path(args)
    state = load_state(path)
    pending = state.get("pending_adjudication")
    if not pending:
        fail("no adjudication is pending")
    if pending.get("outcome") == "blocked":
        fail("adjudication is blocked; a controller decision is required")
    evidence_key = require_text(args.evidence_key, "evidence-key")
    if evidence_key != pending["evidence_key"]:
        fail("judge evidence key does not match the pending adjudication")
    judge_id = require_text(args.judge_id, "judge-id")
    if judge_id == state["manager_id"]:
        fail("Judge identity must be independent from the Issue manager")
    if judge_id == (state.get("worker") or {}).get("id"):
        fail("Judge identity must be independent from the implementation worker")
    if judge_id in state["used_reviewer_ids"]:
        fail("Judge identity must be independent from local reviewers")
    if judge_id in state["used_judge_ids"]:
        fail("Judge identity was already used in this Issue")
    judge_profile = require_text(args.judge_profile, "judge-profile")
    judge_provider = require_text(args.judge_provider, "judge-provider")
    judge_model = require_text(args.judge_model, "judge-model")
    judge_reasoning = require_text(args.judge_reasoning, "judge-reasoning")
    require_route(
        judge_profile,
        judge_model,
        judge_reasoning,
        strict_config(state)["roles"]["judge"],
        "Judge",
    )
    report = require_text(args.report, "report")
    outcome = args.outcome
    record = {
        **pending,
        "judge_id": judge_id,
        "judge_profile": judge_profile,
        "judge_provider": judge_provider,
        "judge_model": judge_model,
        "judge_reasoning": judge_reasoning,
        "judge_report": report,
        "outcome": outcome,
        "completed_at": now_utc(),
    }
    state["adjudications"].append(record)
    state["used_judge_ids"].append(judge_id)
    if outcome == "resolved":
        state["pending_adjudication"] = None
        state["stage"] = pending["resume_stage"]
    else:
        state["pending_adjudication"] = {
            **pending,
            "outcome": "blocked",
            "judge_id": judge_id,
            "judge_report": report,
        }
        state["stage"] = "adjudication_blocked"
    add_event(
        state,
        "adjudication_finished",
        evidence_key=evidence_key,
        judge_id=judge_id,
        outcome=outcome,
        report=report,
    )
    save_state(path, state)
    return state


def cmd_record_worker(args: argparse.Namespace) -> dict[str, Any]:
    path = state_path(args)
    state = load_state(path)
    worker_id = require_text(args.worker_id, "worker-id")
    worker_profile = require_text(args.worker_profile, "worker-profile")
    worker_provider = require_text(args.worker_provider, "worker-provider")
    worker_model = require_text(args.worker_model, "worker-model")
    worker_reasoning = getattr(args, "worker_reasoning", None)
    continuity = require_worker_continuity(args.continuity)
    existing_worker = state["worker"]
    if existing_worker is None:
        if is_strict_state(state):
            require_no_pending_adjudication(state, action="worker selection")
            if state["assessment"] is None:
                fail("record the mandatory implementation assessment before worker selection")
            tier = require_text(args.tier, "tier")
            if tier != state["assessment"]["tier"]:
                fail("worker tier must match the recorded assessment")
            worker_reasoning = require_text(worker_reasoning, "worker-reasoning")
            expected = strict_config(state)["roles"]["worker"]["tiers"][tier]
            require_route(
                worker_profile, worker_model, worker_reasoning, expected, "worker"
            )
        if state["stage"] != "worker_selection" or state.get("implementation_started_at") is not None:
            fail("first-time worker recording is allowed only in worker_selection")
        state["worker"] = {
            "id": worker_id,
            "profile": worker_profile,
            "provider": worker_provider,
            "model": worker_model,
            "reasoning": worker_reasoning,
            "tier": state["assessment"]["tier"] if is_strict_state(state) else None,
            "recorded_at": now_utc(),
        }
        state["worker_continuity"] = continuity
        state["stage"] = "worker_selected"
        add_event(
            state,
            "worker_recorded",
            worker_id=worker_id,
            worker_profile=worker_profile,
            worker_provider=worker_provider,
            worker_model=worker_model,
            worker_reasoning=worker_reasoning,
            continuity=continuity,
        )
        save_state(path, state)
        return state

    if state["worker_continuity"] != continuity:
        fail("worker continuity contract does not match the recorded implementation worker")
    if existing_worker["id"] != worker_id or existing_worker["profile"] != worker_profile:
        fail("implementation worker identity/profile does not match the recorded worker")
    existing_provider = existing_worker.get("provider")
    existing_model = existing_worker.get("model")
    if existing_provider is not None or existing_model is not None:
        fail("implementation worker is already recorded")
    existing_worker["provider"] = worker_provider
    existing_worker["model"] = worker_model
    existing_worker["reasoning"] = worker_reasoning
    existing_worker["enriched_at"] = now_utc()
    add_event(
        state,
        "worker_enriched",
        worker_id=worker_id,
        worker_profile=worker_profile,
        worker_provider=worker_provider,
        worker_model=worker_model,
        worker_reasoning=worker_reasoning,
        continuity=continuity,
    )
    save_state(path, state)
    return state


def cmd_start_implementation(args: argparse.Namespace) -> dict[str, Any]:
    path = state_path(args)
    state = load_state(path)
    if state.get("legacy_in_progress"):
        fail("start-implementation is unavailable for legacy in-progress states")
    require_no_pending_adjudication(state, action="implementation start")
    if state["stage"] != "worker_selected":
        if state["stage"] == "implementing" and state.get("implementation_started_at") is not None:
            fail("implementation is already started")
        require_worker_recorded(state, action="starting implementation")
        fail("implementation can start only after worker selection")
    worker = require_worker_match(state, args)
    started_at = now_utc()
    state["implementation_started_at"] = started_at
    state["stage"] = "implementing"
    add_event(
        state,
        "implementation_started",
        worker_id=worker["id"],
        worker_profile=worker["profile"],
        worker_provider=worker["provider"],
        worker_model=worker["model"],
        worker_reasoning=worker.get("reasoning"),
    )
    save_state(path, state)
    return state


def cmd_start_review(args: argparse.Namespace) -> dict[str, Any]:
    path = state_path(args)
    state = load_state(path)
    require_worker_recorded(state, action="starting review")
    require_implementation_started(state, action="starting review")
    require_no_pending_adjudication(state, action="starting review")
    if state["local_review_closed"]:
        fail("local review is already closed")
    if state["active_review"]:
        fail("a review is already active")
    if state["needs_fix"]:
        fail("record the required worker fix before starting another review")
    max_reviews = review_limit(state)
    if state["review_count"] >= max_reviews:
        fail("review limit reached; another completed review is forbidden")
    reviewer_id = require_text(args.reviewer_id, "reviewer-id")
    reviewer_profile = require_text(args.reviewer_profile, "reviewer-profile")
    if reviewer_id == state["manager_id"]:
        fail("reviewer identity must be independent from the Issue manager")
    if reviewer_id == state["worker"]["id"]:
        fail("reviewer identity must be independent from the implementation worker")
    if reviewer_id in state["used_judge_ids"]:
        fail("reviewer identity must be independent from Judge identities")
    if reviewer_id in state["used_reviewer_ids"]:
        fail("reviewer identity was already used in this Issue")
    reviewer_provider = getattr(args, "reviewer_provider", None)
    reviewer_model = getattr(args, "reviewer_model", None)
    reviewer_reasoning = getattr(args, "reviewer_reasoning", None)
    if is_strict_state(state):
        reviewer_provider = require_text(reviewer_provider, "reviewer-provider")
        reviewer_model = require_text(reviewer_model, "reviewer-model")
        reviewer_reasoning = require_text(reviewer_reasoning, "reviewer-reasoning")
        require_route(
            reviewer_profile,
            reviewer_model,
            reviewer_reasoning,
            strict_config(state)["roles"]["reviewer"],
            "reviewer",
        )
    round_number = state["review_count"] + 1
    state["active_review"] = True
    state["active_review_number"] = round_number
    state["active_reviewer"] = {
        "id": reviewer_id,
        "profile": reviewer_profile,
        "provider": reviewer_provider,
        "model": reviewer_model,
        "reasoning": reviewer_reasoning,
    }
    state["used_reviewer_ids"].append(reviewer_id)
    state["stage"] = "local_review"
    add_event(
        state,
        "review_started",
        round=round_number,
        reviewer_id=reviewer_id,
        reviewer_profile=reviewer_profile,
        reviewer_provider=reviewer_provider,
        reviewer_model=reviewer_model,
        reviewer_reasoning=reviewer_reasoning,
    )
    save_state(path, state)
    return state


def cmd_abort_review(args: argparse.Namespace) -> dict[str, Any]:
    path = state_path(args)
    state = load_state(path)
    if not state["active_review"]:
        fail("no active review to abort")
    reason = require_text(args.reason, "reason")
    round_number = state["active_review_number"]
    reviewer = state["active_reviewer"] or {}
    state["active_review"] = False
    state["active_review_number"] = None
    state["active_reviewer"] = None
    state["stage"] = "awaiting_review"
    add_event(
        state,
        "review_aborted",
        attempted_round=round_number,
        reviewer_id=reviewer.get("id"),
        reviewer_profile=reviewer.get("profile"),
        reason=reason,
    )
    save_state(path, state)
    return state


def cmd_finish_review(args: argparse.Namespace) -> dict[str, Any]:
    path = state_path(args)
    state = load_state(path)
    require_worker_recorded(state, action="finishing review")
    require_implementation_started(state, action="finishing review")
    if not state["active_review"]:
        fail("no active review to finish")
    report = require_text(args.report, "report")
    summary = require_text(args.summary, "summary")
    round_number = state["active_review_number"]
    reviewer = state["active_reviewer"] or {}
    if round_number != state["review_count"] + 1 or round_number > review_limit(state):
        fail("active review number is inconsistent with the completed count")
    state["review_count"] = round_number
    state["active_review"] = False
    state["active_review_number"] = None
    state["active_reviewer"] = None
    state["last_review_outcome"] = args.outcome
    if args.outcome == "pass":
        state["needs_fix"] = False
        state["local_review_closed"] = True
        state["last_local_pass"] = {
            "round": round_number,
            "reviewer_id": reviewer.get("id"),
            "report": report,
            "at": now_utc(),
        }
        state["stage"] = "local_review_complete"
    else:
        state["failed_review_cycles"] += 1
        state["needs_fix"] = True
        state["stage"] = "fixing"
        if is_strict_state(state) and state["failed_review_cycles"] >= 2:
            evidence_key = require_text(
                getattr(args, "adjudication_evidence_key", None),
                "adjudication-evidence-key",
            )
            if any(
                item["evidence_key"] == evidence_key
                for item in state["adjudications"]
            ):
                fail("adjudication evidence key was already resolved")
            state["pending_adjudication"] = {
                "trigger": "failed_review_cycle",
                "evidence_key": evidence_key,
                "evidence": summary,
                "revision": f"local-review-{round_number}",
                "report": report,
                "requested_at": now_utc(),
                "outcome": "pending",
                "resume_stage": "fixing",
            }
            state["stage"] = "adjudication"
    add_event(
        state,
        "review_finished",
        round=round_number,
        reviewer_id=reviewer.get("id"),
        reviewer_profile=reviewer.get("profile"),
        outcome=args.outcome,
        report=report,
        summary=summary,
        failed_review_cycles=state["failed_review_cycles"],
    )
    if state.get("pending_adjudication"):
        add_event(
            state,
            "adjudication_requested",
            trigger=state["pending_adjudication"]["trigger"],
            evidence_key=state["pending_adjudication"]["evidence_key"],
            revision=state["pending_adjudication"]["revision"],
            report=state["pending_adjudication"]["report"],
        )
    save_state(path, state)
    return state


def cmd_record_fix(args: argparse.Namespace) -> dict[str, Any]:
    path = state_path(args)
    state = load_state(path)
    require_implementation_started(state, action="recording a fix")
    require_no_pending_adjudication(state, action="recording a fix")
    if state["active_review"]:
        fail("finish the active review before recording a fix")
    if not state["needs_fix"]:
        fail("no reviewer-requested fix is pending")
    require_worker_match(state, args)
    report = require_text(args.report, "report")
    validation = require_text(args.validation, "validation")
    if is_strict_state(state) and state["review_count"] == review_limit(state):
        fail("strict policy requires a reviewer PASS and no review rounds remain")
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
    require_implementation_started(state, action="recording a PR")
    require_no_pending_adjudication(state, action="recording a PR")
    if is_strict_state(state) and state.get("last_local_pass") is None:
        fail("strict policy requires a configured-reviewer PASS before PR preparation")
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
    state["review_threads_evidence"] = None
    state["stage"] = "pr_draft"
    add_event(state, "pr_recorded", url=url, head_sha=head_sha, closing_reference=closing_reference)
    save_state(path, state)
    return state


def cmd_mark_ready(args: argparse.Namespace) -> dict[str, Any]:
    path = state_path(args)
    state = load_state(path)
    require_no_pending_adjudication(state, action="marking the PR Ready")
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
    require_no_pending_adjudication(state, action="fetching remote feedback")
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
    require_implementation_started(state, action="recording remote assessment")
    require_no_pending_adjudication(state, action="recording remote assessment")
    if state["remote_feedback_fetched_at"] is None:
        fail("record the one allowed remote feedback fetch first")
    if state["remote_assessment"] is not None:
        fail("remote feedback assessment is already recorded")
    require_worker_match(state, args)
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
    require_no_pending_adjudication(state, action="resolving blocked remote feedback")
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
    require_implementation_started(state, action="recording remote fix")
    require_no_pending_adjudication(state, action="recording remote fix")
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
    require_worker_match(state, args)
    head_sha = require_text(args.head_sha, "head-sha")
    validation = require_text(args.validation, "validation")
    if head_sha == state["pr_head_sha"]:
        fail("remote fix must record a new PR HEAD SHA")
    repair_number = state["remote_fix_count"] + 1
    state["pr_head_sha"] = head_sha
    state["checks_passed"] = False
    state["checks_evidence"] = None
    state["review_threads_evidence"] = None
    state["remote_fix_completed_at"] = now_utc()
    state["remote_fix_count"] = repair_number
    state["remote_fixes"].append({"number": repair_number, "head_sha": head_sha, "validation": validation, "at": state["remote_fix_completed_at"]})
    state["stage"] = "merge_ready"
    add_event(state, "remote_fix_recorded", number=repair_number, head_sha=head_sha, validation=validation)
    save_state(path, state)
    return state


def cmd_record_check_repair(args: argparse.Namespace) -> dict[str, Any]:
    path = state_path(args)
    state = load_state(path)
    require_implementation_started(state, action="recording check repair")
    require_no_pending_adjudication(state, action="recording check repair")
    if state["pr_url"] is None:
        fail("record the PR before check repair")
    if state["merged_at"] is not None:
        fail("check repair is not allowed after merge")
    checks = state["checks_evidence"]
    if not checks or checks["result"] != "fail" or checks["head_sha"] != state["pr_head_sha"]:
        fail("check repair requires failed checks on the current PR HEAD")
    require_worker_match(state, args)
    head_sha = require_text(args.head_sha, "head-sha")
    if head_sha == state["pr_head_sha"]:
        fail("check repair must record a new PR HEAD SHA")
    validation = require_text(args.validation, "validation")
    evidence = require_text(args.evidence, "evidence")
    previous_head_sha = state["pr_head_sha"]
    repair_number = state["check_repair_count"] + 1
    state["pr_head_sha"] = head_sha
    state["checks_passed"] = False
    state["checks_evidence"] = None
    state["review_threads_evidence"] = None
    state["check_repair_count"] = repair_number
    state["check_repairs"].append(
        {
            "number": repair_number,
            "previous_head_sha": previous_head_sha,
            "head_sha": head_sha,
            "validation": validation,
            "evidence": evidence,
            "at": now_utc(),
        }
    )
    add_event(
        state,
        "check_repair_recorded",
        number=repair_number,
        previous_head_sha=previous_head_sha,
        head_sha=head_sha,
        validation=validation,
        evidence=evidence,
    )
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


def cmd_record_review_threads(args: argparse.Namespace) -> dict[str, Any]:
    path = state_path(args)
    state = load_state(path)
    if state["pr_url"] is None:
        fail("record the PR before unresolved review threads")
    head_sha = require_text(args.head_sha, "head-sha")
    if head_sha != state["pr_head_sha"]:
        fail("review threads must refer to the current PR HEAD SHA")
    evidence = require_text(args.evidence, "evidence")
    unresolved = args.unresolved_count
    if unresolved < 0:
        fail("unresolved-count must be zero or greater")
    state["review_threads_evidence"] = {
        "head_sha": head_sha,
        "unresolved_count": unresolved,
        "evidence": evidence,
        "at": now_utc(),
    }
    add_event(
        state,
        "review_threads_recorded",
        head_sha=head_sha,
        unresolved_count=unresolved,
        evidence=evidence,
    )
    save_state(path, state)
    return state


def cmd_mark_merged(args: argparse.Namespace) -> dict[str, Any]:
    path = state_path(args)
    state = load_state(path)
    require_no_pending_adjudication(state, action="recording merge")
    if state["stage"] != "merge_ready" or state["remote_assessment"] is None:
        fail("completed remote assessment is required before merge")
    if not state["checks_passed"]:
        fail("current PR HEAD must have passing required checks")
    review_threads = state.get("review_threads_evidence")
    if (
        not review_threads
        or review_threads["head_sha"] != state["pr_head_sha"]
        or review_threads["unresolved_count"] != 0
    ):
        fail("latest review-thread query must report zero unresolved threads for the current PR HEAD")
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
    init.add_argument("--runtime-snapshot")
    init.add_argument("--manager-profile")
    init.add_argument("--manager-model")
    init.add_argument("--manager-reasoning")
    init.set_defaults(handler=cmd_init)

    assessment = commands.add_parser(
        "record-assessment", help="record mandatory implementation tier evidence"
    )
    add_state_file(assessment)
    assessment.add_argument("--affected-modules", required=True)
    assessment.add_argument("--coupling-and-difficulty", required=True)
    assessment.add_argument("--unresolved-decisions", required=True)
    assessment.add_argument("--tier", choices=("simple", "normal", "complex", "extreme"), required=True)
    assessment.add_argument("--validation-plan", required=True)
    assessment.add_argument("--uncertainty-evidence-key")
    assessment.add_argument("--uncertainty-evidence")
    assessment.set_defaults(handler=cmd_record_assessment)

    worker = commands.add_parser("record-worker", help="record the one implementation worker and continuity contract")
    add_state_file(worker)
    add_worker_identity_args(worker)
    worker.add_argument("--tier", choices=("simple", "normal", "complex", "extreme"))
    worker.add_argument("--continuity", required=True)
    worker.set_defaults(handler=cmd_record_worker)

    start_implementation = commands.add_parser("start-implementation", help="record the worker-selected implementation start boundary")
    add_state_file(start_implementation)
    add_worker_identity_args(start_implementation)
    start_implementation.set_defaults(handler=cmd_start_implementation)

    start = commands.add_parser("start-review", help="reserve the next reviewer round")
    add_state_file(start)
    start.add_argument("--reviewer-id", required=True)
    start.add_argument("--reviewer-profile", required=True)
    start.add_argument("--reviewer-provider")
    start.add_argument("--reviewer-model")
    start.add_argument("--reviewer-reasoning")
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
    finish.add_argument("--adjudication-evidence-key")
    finish.set_defaults(handler=cmd_finish_review)

    fix = commands.add_parser("record-fix", help="record the worker fix after findings")
    add_state_file(fix)
    add_worker_identity_args(fix)
    fix.add_argument("--report", required=True)
    fix.add_argument("--validation", required=True)
    fix.set_defaults(handler=cmd_record_fix)

    request_judge = commands.add_parser(
        "request-judge", help="record a concrete disagreement or uncertainty"
    )
    add_state_file(request_judge)
    request_judge.add_argument(
        "--trigger",
        choices=("reviewer_disagreement", "architecture_security_uncertainty"),
        required=True,
    )
    request_judge.add_argument("--evidence-key", required=True)
    request_judge.add_argument("--evidence", required=True)
    request_judge.add_argument("--revision", required=True)
    request_judge.add_argument("--report", required=True)
    request_judge.set_defaults(handler=cmd_request_judge)

    judge = commands.add_parser(
        "record-judge", help="record the separate read-only Judge decision"
    )
    add_state_file(judge)
    judge.add_argument("--judge-id", required=True)
    judge.add_argument("--judge-profile", required=True)
    judge.add_argument("--judge-provider", required=True)
    judge.add_argument("--judge-model", required=True)
    judge.add_argument("--judge-reasoning", required=True)
    judge.add_argument("--evidence-key", required=True)
    judge.add_argument("--report", required=True)
    judge.add_argument("--outcome", choices=("resolved", "blocked"), required=True)
    judge.set_defaults(handler=cmd_record_judge)

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
    add_worker_identity_args(assessment)
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
    add_worker_identity_args(remote_fix)
    remote_fix.add_argument("--head-sha", required=True)
    remote_fix.add_argument("--validation", required=True)
    remote_fix.set_defaults(handler=cmd_record_remote_fix)

    check_repair = commands.add_parser("record-check-repair", help="record an Issue-caused repair for failed checks on the current PR HEAD")
    add_state_file(check_repair)
    add_worker_identity_args(check_repair)
    check_repair.add_argument("--head-sha", required=True)
    check_repair.add_argument("--validation", required=True)
    check_repair.add_argument("--evidence", required=True)
    check_repair.set_defaults(handler=cmd_record_check_repair)

    checks = commands.add_parser("record-checks", help="record required checks for current PR HEAD")
    add_state_file(checks)
    checks.add_argument("--head-sha", required=True)
    checks.add_argument("--result", choices=("pass", "fail"), required=True)
    checks.add_argument("--evidence", required=True)
    checks.set_defaults(handler=cmd_record_checks)

    review_threads = commands.add_parser("record-review-threads", help="record unresolved review-thread count for current PR HEAD")
    add_state_file(review_threads)
    review_threads.add_argument("--head-sha", required=True)
    review_threads.add_argument("--unresolved-count", type=int, required=True)
    review_threads.add_argument("--evidence", required=True)
    review_threads.set_defaults(handler=cmd_record_review_threads)

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
