from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


runtime_config = load_module("runtime_config", ROOT / "scripts" / "runtime_config.py")
review_cycle = load_module("review_cycle_strict", ROOT / "scripts" / "review_cycle.py")


class RuntimeOnboardingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.selection = self.directory / "selection.json"
        self.preset = ROOT / "config" / "runtimes" / "codex.json"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write(self, name: str, value: dict) -> Path:
        path = self.directory / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def capabilities(self) -> dict:
        return {
            "runtime": "codex",
            "max_children": 4,
            "fast_mode": False,
            "persistent_worker": True,
            "fresh_isolated_reviewers": True,
            "evidence": "inspected current Codex host task and role metadata",
            "models": {
                "gpt-5.6-sol": ["medium", "high"],
                "gpt-5.6-luna": ["low", "medium"],
                "gpt-5.6-terra": ["medium"],
                "gpt-6-astra": ["high"],
            },
        }

    def current_codex_capabilities(self, manager_model: str = "current-manager") -> dict:
        capabilities = self.capabilities()
        capabilities["models"].update(
            {
                manager_model: ["medium"],
                "current-worker": ["medium"],
                "current-reviewer": ["high"],
            }
        )
        capabilities["current_routes"] = {
            "manager": {
                "role": "manager", "model": manager_model, "reasoning": "medium"
            },
            "worker": {
                "tiers": {
                    tier: {
                        "role": (
                            "worker" if tier in {"simple", "normal"}
                            else "senior_worker" if tier == "complex"
                            else "expert_worker"
                        ),
                        "model": "current-worker",
                        "reasoning": "medium",
                    }
                    for tier in ("simple", "normal", "complex", "extreme")
                }
            },
            "reviewer": {
                "role": "reviewer",
                "model": "current-reviewer",
                "reasoning": "high",
            },
        }
        return capabilities

    def test_first_use_requires_selection(self) -> None:
        result = runtime_config.resolve_selection(self.selection)
        self.assertEqual("setup_required", result["status"])
        self.assertEqual(
            {"current", "tiered", "custom"},
            {item["strategy"] for item in result["options"]},
        )

    def test_current_selection_requires_preview_and_rebinds_each_issue(self) -> None:
        with self.assertRaisesRegex(runtime_config.ConfigError, "--capabilities"):
            runtime_config.select_runtime(self.selection, "codex", "current")
        incomplete = self.write(
            "incomplete-current.json",
            {
                "runtime": "codex",
                "max_children": 4,
                "persistent_worker": True,
                "fresh_isolated_reviewers": True,
                "evidence": "current task inspected",
                "models": {},
            },
        )
        with self.assertRaisesRegex(runtime_config.ConfigError, "current_routes"):
            runtime_config.preview_current("codex", incomplete)

        first_capabilities = self.write(
            "current-first.json", self.current_codex_capabilities()
        )
        preview = runtime_config.preview_current("codex", first_capabilities)
        self.assertFalse(self.selection.exists())
        self.assertEqual(
            "current-manager", preview["roles"]["manager"]["model"]
        )
        selection = runtime_config.select_runtime(
            self.selection,
            "codex",
            "current",
            capabilities_path=first_capabilities,
        )
        self.assertIsNone(
            selection["effective_config"]["roles"]["manager"]["model"]
        )
        self.assertEqual(
            "current-manager",
            selection["current_preview"]["roles"]["manager"]["model"],
        )

        changed_capabilities = self.current_codex_capabilities("new-current-manager")
        changed_capabilities["max_children"] = 2
        second_capabilities = self.write("current-second.json", changed_capabilities)
        snapshot = runtime_config.preflight(
            self.selection, None, None, second_capabilities
        )
        self.assertEqual(
            "new-current-manager",
            snapshot["effective_config"]["roles"]["manager"]["model"],
        )
        self.assertEqual("medium", snapshot["effective_config"]["roles"]["manager"]["reasoning"])
        self.assertEqual(2, snapshot["effective_config"]["constraints"]["max_children"])
        self.assertIs(snapshot["effective_config"]["constraints"]["fast_mode"], False)
        saved = json.loads(self.selection.read_text(encoding="utf-8"))
        self.assertEqual("current", saved["strategy"])
        self.assertIsNone(saved["effective_config"]["roles"]["manager"]["model"])

        del saved["current_preview"]
        self.selection.write_text(json.dumps(saved), encoding="utf-8")
        legacy_snapshot = runtime_config.preflight(
            self.selection, None, None, second_capabilities
        )
        self.assertEqual(
            "new-current-manager",
            legacy_snapshot["effective_config"]["roles"]["manager"]["model"],
        )

        missing_route = self.current_codex_capabilities()
        del missing_route["current_routes"]["reviewer"]["reasoning"]
        missing_route_path = self.write("current-missing-route.json", missing_route)
        with self.assertRaisesRegex(runtime_config.ConfigError, "reviewer.reasoning"):
            runtime_config.preflight(
                self.selection, None, None, missing_route_path
            )

        unavailable = self.current_codex_capabilities()
        del unavailable["models"]["current-reviewer"]
        unavailable_path = self.write("current-unavailable.json", unavailable)
        with self.assertRaisesRegex(runtime_config.ConfigError, "reviewer route"):
            runtime_config.preflight(
                self.selection, None, None, unavailable_path
            )

    def test_partial_custom_inheritance_keeps_explicit_route_precedence(self) -> None:
        custom = runtime_config.current_config("codex")
        custom["selection_strategy"] = "custom"
        custom["roles"]["manager"]["model"] = "current-manager"
        custom_path = self.write("partial-custom.json", custom)
        runtime_config.select_runtime(
            self.selection, "codex", "custom", custom_path
        )
        capabilities_path = self.write(
            "partial-current.json", self.current_codex_capabilities()
        )
        snapshot = runtime_config.preflight(
            self.selection, None, None, capabilities_path
        )
        self.assertEqual(
            ("current-manager", "medium"),
            (
                snapshot["effective_config"]["roles"]["manager"]["model"],
                snapshot["effective_config"]["roles"]["manager"]["reasoning"],
            ),
        )

        conflicting = self.current_codex_capabilities("different-manager")
        conflict_path = self.write("partial-conflict.json", conflicting)
        with self.assertRaisesRegex(runtime_config.ConfigError, "selected explicit value"):
            runtime_config.preflight(self.selection, None, None, conflict_path)

    def test_saved_selection_is_reused_without_preset_drift(self) -> None:
        preset_copy = self.write(
            "codex.json", json.loads(self.preset.read_text(encoding="utf-8"))
        )
        runtime_config.select_runtime(
            self.selection, "codex", "tiered", preset_copy
        )
        first = runtime_config.resolve_selection(self.selection)
        changed = json.loads(preset_copy.read_text(encoding="utf-8"))
        changed["roles"]["manager"]["model"] = "changed-later"
        preset_copy.write_text(json.dumps(changed), encoding="utf-8")
        second = runtime_config.resolve_selection(self.selection)
        self.assertEqual(
            "gpt-5.6-sol",
            first["effective_config"]["roles"]["manager"]["model"],
        )
        self.assertEqual(first["effective_config"], second["effective_config"])

    def test_explicit_override_has_precedence_and_preserves_null(self) -> None:
        custom = runtime_config.current_config("codex")
        custom["selection_strategy"] = "custom"
        custom["roles"]["manager"]["model"] = "configured-manager"
        custom["roles"]["manager"]["reasoning"] = "medium"
        custom_path = self.write("non-strict-custom.json", custom)
        runtime_config.select_runtime(
            self.selection, "codex", "custom", custom_path
        )
        override = self.write(
            "override.json",
            {"roles": {"manager": {"model": None, "reasoning": None}}},
        )
        result = runtime_config.resolve_selection(self.selection, override_path=override)
        self.assertIsNone(result["effective_config"]["roles"]["manager"]["model"])
        self.assertIsNone(result["effective_config"]["roles"]["manager"]["reasoning"])

    def test_invalid_saved_selection_fails_instead_of_falling_back(self) -> None:
        self.selection.write_text("{bad json", encoding="utf-8")
        with self.assertRaisesRegex(runtime_config.ConfigError, "cannot read selection"):
            runtime_config.resolve_selection(self.selection)

    def test_custom_config_can_keep_strict_gates_with_customer_routes(self) -> None:
        custom = json.loads(self.preset.read_text(encoding="utf-8"))
        custom["constraints"]["max_children"] = 7
        custom["roles"]["manager"]["model"] = "customer-manager"
        custom_path = self.write("custom.json", custom)
        selection = runtime_config.select_runtime(
            self.selection, "codex", "custom", custom_path
        )
        self.assertTrue(
            selection["effective_config"]["policy"]["strict_lifecycle"]
        )
        self.assertEqual(
            7, selection["effective_config"]["constraints"]["max_children"]
        )

    def test_non_strict_custom_rejects_strict_only_policy_fields(self) -> None:
        for field in ("assessment_required", "local_pass_required"):
            with self.subTest(field=field):
                custom = json.loads(self.preset.read_text(encoding="utf-8"))
                custom["selection_strategy"] = "custom"
                custom["policy"]["strict_lifecycle"] = False
                custom["policy"]["assessment_required"] = False
                custom["policy"]["local_pass_required"] = False
                del custom["policy"]["judge"]
                custom["policy"][field] = True
                with self.assertRaisesRegex(
                    runtime_config.ConfigError,
                    rf"policy\.{field} must be false",
                ):
                    runtime_config.validate_config(custom)

        retained_judge = json.loads(self.preset.read_text(encoding="utf-8"))
        retained_judge["selection_strategy"] = "custom"
        retained_judge["policy"]["strict_lifecycle"] = False
        retained_judge["policy"]["assessment_required"] = False
        retained_judge["policy"]["local_pass_required"] = False
        with self.assertRaisesRegex(
            runtime_config.ConfigError,
            "policy.judge must be omitted",
        ):
            runtime_config.validate_config(retained_judge)

        runtime_config.validate_config(runtime_config.current_config("codex"))
        runtime_config.load_config(
            ROOT / "config" / "runtimes" / "hermes.json", "hermes"
        )

    def test_shipped_codex_routes_match_the_offered_tiered_choice(self) -> None:
        config = runtime_config.load_config(self.preset, "codex")
        self.assertEqual(
            ("gpt-5.6-sol", "medium"),
            (
                config["roles"]["manager"]["model"],
                config["roles"]["manager"]["reasoning"],
            ),
        )
        expected = {
            "simple": ("worker", "gpt-5.6-terra", "medium"),
            "normal": ("worker", "gpt-5.6-terra", "medium"),
            "complex": ("senior_worker", "gpt-5.6-sol", "high"),
            "extreme": ("expert_worker", "gpt-6-astra", "high"),
        }
        for tier, route in expected.items():
            actual = config["roles"]["worker"]["tiers"][tier]
            self.assertEqual(route, (actual["role"], actual["model"], actual["reasoning"]))
        for name, route in {
            "researcher": ("gpt-5.6-luna", "low"),
            "explorer": ("gpt-5.6-luna", "medium"),
            "reviewer": ("gpt-5.6-sol", "high"),
            "senior_reviewer": ("gpt-5.6-sol", "high"),
            "judge": ("gpt-6-astra", "high"),
            "architect": ("gpt-6-astra", "high"),
        }.items():
            self.assertEqual(
                route,
                (config["roles"][name]["model"], config["roles"][name]["reasoning"]),
            )
        self.assertEqual(4, config["constraints"]["max_children"])
        self.assertIs(config["constraints"]["fast_mode"], False)

    def test_strict_policy_requires_explicit_judge_model_and_reasoning(self) -> None:
        for fields in (("model",), ("reasoning",), ("model", "reasoning")):
            with self.subTest(fields=fields):
                config = runtime_config.load_config(self.preset, "codex")
                for field in fields:
                    config["roles"]["judge"][field] = None
                with self.assertRaisesRegex(
                    runtime_config.ConfigError,
                    "roles.judge must select an explicit model and reasoning",
                ):
                    runtime_config.validate_config(config)

    def test_preflight_requires_actual_route_and_fast_evidence(self) -> None:
        runtime_config.select_runtime(self.selection, "codex", "tiered", self.preset)
        capabilities = self.capabilities()
        capabilities["fast_mode"] = True
        path = self.write("capabilities.json", capabilities)
        with self.assertRaisesRegex(runtime_config.ConfigError, "fast_mode=false"):
            runtime_config.preflight(self.selection, None, None, path)
        capabilities["fast_mode"] = False
        capabilities["models"]["gpt-6-astra"] = ["medium"]
        path.write_text(json.dumps(capabilities), encoding="utf-8")
        with self.assertRaisesRegex(runtime_config.ConfigError, "worker.extreme"):
            runtime_config.preflight(self.selection, None, None, path)

    def test_legacy_migration_preserves_strings_and_nulls(self) -> None:
        legacy = self.write(
            "models.json",
            {
                "manager": "custom-manager",
                "worker": None,
                "reviewer": "custom-reviewer",
                "remote_worker": None,
            },
        )
        candidate = runtime_config.migrate_legacy(legacy, "codex", None)
        self.assertEqual(
            "custom-manager", candidate["roles"]["manager"]["model"]
        )
        self.assertIsNone(
            candidate["roles"]["worker"]["tiers"]["normal"]["model"]
        )
        self.assertEqual(
            "custom-reviewer", candidate["roles"]["reviewer"]["model"]
        )
        self.assertEqual(
            {
                "manager": "custom-manager",
                "worker": None,
                "reviewer": "custom-reviewer",
                "remote_worker": None,
            },
            candidate["legacy_migration"]["preserved_values"],
        )

    def test_legacy_empty_and_remote_worker_switch_are_rejected(self) -> None:
        empty = self.write(
            "empty.json",
            {"manager": "", "worker": None, "reviewer": None, "remote_worker": None},
        )
        with self.assertRaisesRegex(runtime_config.ConfigError, "non-empty"):
            runtime_config.migrate_legacy(empty, "codex", None)
        conflict = self.write(
            "conflict.json",
            {
                "manager": None,
                "worker": "worker-a",
                "reviewer": None,
                "remote_worker": "worker-b",
            },
        )
        with self.assertRaisesRegex(runtime_config.ConfigError, "must match worker"):
            runtime_config.migrate_legacy(conflict, "codex", None)

    def test_hermes_current_requires_nested_delegation_without_fixing_profiles(self) -> None:
        current_routes = {
            "manager": {
                "role": "manager",
                "profile": "manager-current",
                "provider": "provider-a",
                "model": "manager-model",
            },
            "worker": {
                "tiers": {
                    tier: {
                        "role": "worker",
                        "profile": f"worker-{tier}",
                        "provider": "provider-a",
                        "model": "worker-model",
                    }
                    for tier in ("simple", "normal", "complex")
                }
            },
            "reviewer": {
                "role": "reviewer",
                "profile": "reviewer-current",
                "provider": "provider-a",
                "model": "reviewer-model",
            },
        }
        capabilities = {
            "runtime": "hermes",
            "max_children": 1,
            "persistent_worker": True,
            "fresh_isolated_reviewers": True,
            "evidence": "inspected Hermes delegation configuration",
            "current_routes": current_routes,
            "profiles": {
                route["profile"]: {
                    "provider": route["provider"],
                    "model": route["model"],
                }
                for route in (
                    [current_routes["manager"], current_routes["reviewer"]]
                    + list(current_routes["worker"]["tiers"].values())
                )
            },
        }
        path = self.write("hermes-capabilities.json", capabilities)
        with self.assertRaisesRegex(runtime_config.ConfigError, "nested delegation"):
            runtime_config.preview_current("hermes", path)
        capabilities["nested_delegation"] = True
        capabilities["max_spawn_depth"] = 1
        path.write_text(json.dumps(capabilities), encoding="utf-8")
        with self.assertRaisesRegex(runtime_config.ConfigError, "max_spawn_depth"):
            runtime_config.preview_current("hermes", path)
        capabilities["max_spawn_depth"] = 2
        path.write_text(json.dumps(capabilities), encoding="utf-8")
        runtime_config.select_runtime(
            self.selection,
            "hermes",
            "current",
            capabilities_path=path,
        )
        resolved = runtime_config.resolve_selection(self.selection)
        self.assertIsNone(
            resolved["effective_config"]["roles"]["manager"]["profile"]
        )
        snapshot = runtime_config.preflight(self.selection, None, None, path)
        self.assertEqual("ready", snapshot["status"])
        self.assertEqual(
            ("manager-current", "provider-a", "manager-model"),
            (
                snapshot["effective_config"]["roles"]["manager"]["profile"],
                snapshot["effective_config"]["roles"]["manager"]["provider"],
                snapshot["effective_config"]["roles"]["manager"]["model"],
            ),
        )

    def test_manager_command_sequence_records_review_threads_before_merge(self) -> None:
        prompt = (
            ROOT / "references" / "issue-manager-prompt.md"
        ).read_text(encoding="utf-8")
        sequence = prompt.split("## State-script command sequence", 1)[1]
        self.assertLess(
            sequence.index("record-review-threads --state-file"),
            sequence.index("mark-merged --state-file"),
        )


class StrictLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.state = self.directory / "issue.json"
        config = runtime_config.load_config(
            ROOT / "config" / "runtimes" / "codex.json"
        )
        config = copy.deepcopy(config)
        config["policy"]["review_limit"] = 2
        capabilities = {
            "runtime": "codex",
            "max_children": 4,
            "fast_mode": False,
            "persistent_worker": True,
            "fresh_isolated_reviewers": True,
            "evidence": "test host evidence",
            "models": {
                "gpt-5.6-sol": ["medium", "high"],
                "gpt-5.6-luna": ["low", "medium"],
                "gpt-5.6-terra": ["medium"],
                "gpt-6-astra": ["high"],
            },
        }
        validation = runtime_config.validate_capabilities(config, capabilities)
        snapshot = {
            "snapshot_schema_version": 1,
            "status": "ready",
            "created_at": runtime_config.now_utc(),
            "runtime": "codex",
            "policy_version": config["policy"]["id"],
            "effective_config": config,
            "sources": {},
            "host_validation": validation,
        }
        self.snapshot = self.directory / "snapshot.json"
        self.snapshot.write_text(json.dumps(snapshot), encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def call(self, function, **values):
        return function(argparse.Namespace(state_file=str(self.state), **values))

    def init(self) -> None:
        self.call(
            review_cycle.cmd_init,
            issue="41",
            branch="agent/issue-41",
            manager_id="manager-1",
            runtime_snapshot=str(self.snapshot),
            manager_profile="manager",
            manager_model="gpt-5.6-sol",
            manager_reasoning="medium",
        )

    def worker_args(self) -> dict:
        return {
            "worker_id": "worker-1",
            "worker_profile": "senior_worker",
            "worker_provider": "openai",
            "worker_model": "gpt-5.6-sol",
            "worker_reasoning": "high",
        }

    def test_manager_route_and_frozen_snapshot_are_enforced(self) -> None:
        with self.assertRaisesRegex(SystemExit, "manager route"):
            self.call(
                review_cycle.cmd_init,
                issue="41",
                branch="agent/issue-41",
                manager_id="manager-1",
                runtime_snapshot=str(self.snapshot),
                manager_profile="manager",
                manager_model="gpt-6-astra",
                manager_reasoning="high",
            )
        self.init()
        state = json.loads(self.state.read_text(encoding="utf-8"))
        state["runtime_snapshot"]["effective_config"]["roles"]["manager"][
            "model"
        ] = "modified-after-init"
        self.state.write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaisesRegex(SystemExit, "snapshot.*modified"):
            self.call(review_cycle.cmd_status)

    def reviewer_args(self, reviewer_id: str) -> dict:
        return {
            "reviewer_id": reviewer_id,
            "reviewer_profile": "reviewer",
            "reviewer_provider": "openai",
            "reviewer_model": "gpt-5.6-sol",
            "reviewer_reasoning": "high",
        }

    def prepare_worker(self) -> None:
        self.init()
        self.call(
            review_cycle.cmd_record_assessment,
            affected_modules="runtime resolver and state helper",
            coupling_and_difficulty="crosscrossnot",
            unresolved_decisions="none",
            tier="complex",
            validation_plan="unit and CLI lifecycle tests",
            uncertainty_evidence_key=None,
            uncertainty_evidence=None,
        )
        self.call(
            review_cycle.cmd_record_worker,
            **self.worker_args(),
            tier="complex",
            continuity="worker_identity_profile",
        )
        self.call(review_cycle.cmd_start_implementation, **self.worker_args())

    def test_assessment_and_exact_worker_route_are_mandatory(self) -> None:
        self.init()
        with self.assertRaisesRegex(SystemExit, "assessment"):
            self.call(
                review_cycle.cmd_record_worker,
                **self.worker_args(),
                tier="complex",
                continuity="worker_identity_profile",
            )
        self.call(
            review_cycle.cmd_record_assessment,
            affected_modules="a.py",
            coupling_and_difficulty="cross-module state handling",
            unresolved_decisions="none",
            tier="complex",
            validation_plan="unit tests",
            uncertainty_evidence_key=None,
            uncertainty_evidence=None,
        )
        wrong = self.worker_args()
        wrong["worker_reasoning"] = "medium"
        with self.assertRaisesRegex(SystemExit, "route must be"):
            self.call(
                review_cycle.cmd_record_worker,
                **wrong,
                tier="complex",
                continuity="worker_identity_profile",
            )

    def test_reviewer_must_be_fresh_independent_and_on_route(self) -> None:
        self.prepare_worker()
        with self.assertRaisesRegex(SystemExit, "Issue manager"):
            self.call(
                review_cycle.cmd_start_review,
                **self.reviewer_args("manager-1"),
            )
        with self.assertRaisesRegex(SystemExit, "independent"):
            self.call(
                review_cycle.cmd_start_review,
                **self.reviewer_args("worker-1"),
            )
        wrong = self.reviewer_args("reviewer-1")
        wrong["reviewer_model"] = "gpt-6-astra"
        with self.assertRaisesRegex(SystemExit, "reviewer route"):
            self.call(review_cycle.cmd_start_review, **wrong)
        self.call(
            review_cycle.cmd_start_review, **self.reviewer_args("reviewer-1")
        )
        self.call(review_cycle.cmd_abort_review, reason="runtime tool error")
        state = self.call(review_cycle.cmd_status)
        self.assertEqual(0, state["review_count"])
        with self.assertRaisesRegex(SystemExit, "already used"):
            self.call(
                review_cycle.cmd_start_review,
                **self.reviewer_args("reviewer-1"),
            )

    def test_second_changes_requires_separate_judge_and_pass_remains_required(self) -> None:
        snapshot = json.loads(self.snapshot.read_text(encoding="utf-8"))
        snapshot["effective_config"]["roles"]["judge"]["model"] = "customer-judge"
        snapshot["effective_config"]["roles"]["judge"]["reasoning"] = "xhigh"
        capabilities = {
            "runtime": "codex",
            "max_children": 4,
            "fast_mode": False,
            "persistent_worker": True,
            "fresh_isolated_reviewers": True,
            "evidence": "test host evidence with custom Judge route",
            "models": {
                "gpt-5.6-sol": ["medium", "high"],
                "gpt-5.6-luna": ["low", "medium"],
                "gpt-5.6-terra": ["medium"],
                "gpt-6-astra": ["high"],
                "customer-judge": ["xhigh"],
            },
        }
        snapshot["host_validation"] = runtime_config.validate_capabilities(
            snapshot["effective_config"], capabilities
        )
        self.snapshot.write_text(json.dumps(snapshot), encoding="utf-8")
        self.prepare_worker()
        self.call(
            review_cycle.cmd_start_review, **self.reviewer_args("reviewer-1")
        )
        self.call(
            review_cycle.cmd_finish_review,
            outcome="changes",
            report="review-1.md",
            summary="one mapped defect",
            adjudication_evidence_key=None,
        )
        self.call(
            review_cycle.cmd_record_fix,
            **self.worker_args(),
            report="fix-1.md",
            validation="tests passed",
        )
        self.call(
            review_cycle.cmd_start_review, **self.reviewer_args("reviewer-2")
        )
        self.call(
            review_cycle.cmd_finish_review,
            outcome="changes",
            report="review-2.md",
            summary="second mapped defect",
            adjudication_evidence_key="review-cycle-2",
        )
        with self.assertRaisesRegex(SystemExit, "pending adjudication"):
            self.call(
                review_cycle.cmd_record_fix,
                **self.worker_args(),
                report="fix-2.md",
                validation="tests passed",
            )
        with self.assertRaisesRegex(SystemExit, "independent"):
            self.call(
                review_cycle.cmd_record_judge,
                judge_id="worker-1",
                judge_profile="judge",
                judge_provider="openai",
                judge_model="customer-judge",
                judge_reasoning="xhigh",
                evidence_key="review-cycle-2",
                report="judge.md",
                outcome="resolved",
            )
        with self.assertRaisesRegex(SystemExit, "Issue manager"):
            self.call(
                review_cycle.cmd_record_judge,
                judge_id="manager-1",
                judge_profile="judge",
                judge_provider="openai",
                judge_model="customer-judge",
                judge_reasoning="xhigh",
                evidence_key="review-cycle-2",
                report="judge.md",
                outcome="resolved",
            )
        self.call(
            review_cycle.cmd_record_judge,
            judge_id="judge-1",
            judge_profile="judge",
            judge_provider="openai",
            judge_model="customer-judge",
            judge_reasoning="xhigh",
            evidence_key="review-cycle-2",
            report="judge.md",
            outcome="resolved",
        )
        with self.assertRaisesRegex(SystemExit, "requires a reviewer PASS"):
            self.call(
                review_cycle.cmd_record_fix,
                **self.worker_args(),
                report="fix-2.md",
                validation="tests passed",
            )
        with self.assertRaisesRegex(SystemExit, "reviewer PASS"):
            self.call(
                review_cycle.cmd_record_pr,
                url="https://example.test/pr/1",
                head_sha="abc",
                closing_reference="Closes #41",
            )

    def test_declared_remote_disagreement_blocks_disposition_until_judge(self) -> None:
        self.prepare_worker()
        self.call(
            review_cycle.cmd_start_review, **self.reviewer_args("reviewer-1")
        )
        self.call(
            review_cycle.cmd_finish_review,
            outcome="pass",
            report="review-pass.md",
            summary="no mapped findings",
            adjudication_evidence_key=None,
        )
        self.call(
            review_cycle.cmd_record_pr,
            url="https://example.test/pr/1",
            head_sha="abc",
            closing_reference="Closes #41",
        )
        self.call(review_cycle.cmd_mark_ready)
        state = json.loads(self.state.read_text(encoding="utf-8"))
        state["remote_feedback_started_at"] = "2020-01-01T00:00:00+00:00"
        self.state.write_text(json.dumps(state), encoding="utf-8")
        self.call(review_cycle.cmd_mark_feedback_fetched, snapshot="feedback.json")
        self.call(
            review_cycle.cmd_record_remote_assessment,
            **self.worker_args(),
            outcome="blocked",
            report="remote.md",
        )
        self.call(
            review_cycle.cmd_request_judge,
            trigger="reviewer_disagreement",
            evidence_key="remote-thread-7",
            evidence="worker and reviewer disagree on an AC-2 contract",
            revision="abc",
            report="remote.md",
        )
        with self.assertRaisesRegex(SystemExit, "pending adjudication"):
            self.call(
                review_cycle.cmd_resolve_blocked,
                decision="merge",
                evidence="controller decision",
            )
        self.call(
            review_cycle.cmd_record_judge,
            judge_id="judge-remote",
            judge_profile="judge",
            judge_provider="openai",
            judge_model="gpt-6-astra",
            judge_reasoning="high",
            evidence_key="remote-thread-7",
            report="judge-remote.md",
            outcome="resolved",
        )
        state = self.call(
            review_cycle.cmd_resolve_blocked,
            decision="merge",
            evidence="Judge resolved the concrete disagreement",
        )
        self.assertEqual("merge_ready", state["stage"])


if __name__ == "__main__":
    unittest.main()
