from __future__ import annotations

import copy
import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "typesafe_shadow", ROOT / "scripts" / "typesafe_shadow.py"
)
typesafe_shadow = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(typesafe_shadow)


class TypeSafeShadowTests(unittest.TestCase):
    def test_request_omits_labels_and_result_keeps_predictions_separate(self) -> None:
        packet = {
            "schema_version": 1,
            "case_id": "issue-123",
            "acceptance_criteria": [{"id": "AC-1", "text": "Prevent duplicate processing."}],
            "findings": [
                {
                    "id": "F-1",
                    "claimed_criterion": "AC-1",
                    "category": "workflow",
                    "summary": "The same event can be processed twice.",
                    "reproduction": "Submit the same event twice.",
                    "expected": "The event is processed once.",
                    "actual": "Two records are created.",
                    "evidence": "The report includes both returned record IDs.",
                    "human_disposition": "valid",
                }
            ],
        }
        case, state = typesafe_shadow.validate_packet(copy.deepcopy(packet))
        payload = typesafe_shadow.build_request(state)
        self.assertNotIn("human_disposition", payload["state"]["findings"][0])
        self.assertEqual(3, len(payload["questions"]))

        response = {
            "model": "jev-test",
            "usage": {"input_tokens": 100, "output_tokens": 20},
            "answers": {
                "finding_0_criterion_mapping": {"type": "noul", "noul": 0.91},
                "finding_0_reproduction_evidence": {"type": "noul", "noul": 0.84},
                "finding_0_policy_disposition": {
                    "type": "choice",
                    "choice": "in_scope",
                    "probabilities": {
                        "in_scope": 0.9,
                        "out_of_scope": 0.02,
                        "insufficient_evidence": 0.08,
                    },
                    "confidence": 0.87,
                },
            },
        }
        result = typesafe_shadow.build_result(case, payload, response, b"packet")
        self.assertEqual("valid", result["findings"][0]["human_disposition"])
        self.assertEqual("valid", result["findings"][0]["shadow_label"])
        self.assertTrue(result["findings"][0]["matches_human_label"])
        self.assertEqual(0.91, result["findings"][0]["answers"]["criterion_mapping"]["noul"])
        self.assertNotIn("final_disposition", result["findings"][0])

    def test_malformed_type_safe_choice_is_rejected(self) -> None:
        packet = {
            "schema_version": 1,
            "case_id": "issue-123",
            "acceptance_criteria": [{"id": "AC-1", "text": "Prevent duplicates."}],
            "findings": [{
                "id": "F-1", "claimed_criterion": "AC-1", "category": "workflow",
                "summary": "A duplicate is created.", "reproduction": "Submit twice.",
                "expected": "One record.", "actual": "Two records.", "evidence": "Both IDs are in the report.",
                "human_disposition": "valid",
            }],
        }
        case, state = typesafe_shadow.validate_packet(packet)
        payload = typesafe_shadow.build_request(state)
        response = {
            "model": "jev-test",
            "usage": {},
            "answers": {
                "finding_0_criterion_mapping": {"type": "noul", "noul": 0.9},
                "finding_0_reproduction_evidence": {"type": "noul", "noul": 0.9},
                "finding_0_policy_disposition": {
                    "type": "choice", "choice": [],
                    "probabilities": {"in_scope": 0.9, "out_of_scope": 0.05, "insufficient_evidence": 0.05},
                    "confidence": 0.9,
                },
            },
        }
        with self.assertRaisesRegex(typesafe_shadow.EvaluationError, "invalid policy choice"):
            typesafe_shadow.build_result(case, payload, response, b"packet")

    def test_result_must_be_outside_target_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            checkout = Path(temp) / "checkout"
            checkout.mkdir()
            with self.assertRaisesRegex(typesafe_shadow.EvaluationError, "outside"):
                typesafe_shadow.require_external_output(
                    checkout / "result.json", checkout / "packet.json", checkout
                )

    def test_input_must_be_outside_target_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            checkout = Path(temp) / "checkout"
            checkout.mkdir()
            with self.assertRaisesRegex(typesafe_shadow.EvaluationError, "--input"):
                typesafe_shadow.require_external_output(
                    Path(temp) / "result.json", checkout / "packet.json", checkout
                )


if __name__ == "__main__":
    unittest.main()
