import unittest

from research.development_v1_3 import (
    REPAIR_BLOCK_ID,
    _canonical_number,
    _current_asset_constraint,
    _validate_spec,
    build_damaged_blocks,
)


class DevelopmentV13Test(unittest.TestCase):
    def setUp(self) -> None:
        self.block = {
            "block_id": REPAIR_BLOCK_ID,
            "document_id": "AMD_2022_10K",
            "page_number": 56,
            "text": (
                "Cash and cash equivalents $ 4,835 $ 2,535 "
                "Short-term investments 1,020 1,073 "
                "Accounts receivable, net 4,126 2,706 "
                "Inventories 3,771 1,955 "
                "Receivables from related parties 2 2 "
                "Prepaid expenses and other current assets 1,265 312 "
                "Total current assets 15,019 8,583"
            ),
            "source_kind": "pypdf_page_text",
        }

    def test_controlled_states_change_only_predeclared_values(self) -> None:
        damaged, labels = build_damaged_blocks([self.block], ())
        a_only, _ = build_damaged_blocks([self.block], ("A",))
        b_only, _ = build_damaged_blocks([self.block], ("B",))
        both, _ = build_damaged_blocks([self.block], ("A", "B"))
        self.assertIn("$ 835 $ 2,535", damaged[0]["text"])
        self.assertIn("net 126 2,706", damaged[0]["text"])
        self.assertIn("$ 4,835 $ 2,535", a_only[0]["text"])
        self.assertIn("net 126 2,706", a_only[0]["text"])
        self.assertIn("$ 835 $ 2,535", b_only[0]["text"])
        self.assertIn("net 4,126 2,706", b_only[0]["text"])
        self.assertEqual(both[0]["text"], self.block["text"])
        for label in ("A", "B"):
            row = labels[label]
            self.assertEqual(
                damaged[0]["text"][row["start"] : row["end"]], row["observed_text"]
            )

    def test_accounting_residual_observes_damage_without_gold_values(self) -> None:
        damaged, _ = build_damaged_blocks([self.block], ())
        # Minimal numeric candidates covering every number span.
        import re

        candidates = []
        for index, match in enumerate(re.finditer(r"\d[\d,]*", damaged[0]["text"])):
            candidates.append(
                {
                    "candidate_id": f"c{index}",
                    "start": match.start(),
                    "end": match.end(),
                }
            )
        result = _current_asset_constraint(damaged[0], candidates)
        self.assertAlmostEqual(result["normalized_residuals"][0], 8000 / 15019, places=8)
        self.assertEqual(result["normalized_residuals"][1], 0.0)
        self.assertGreater(len(result["participant_candidate_residuals"]), 0)

    def test_numeric_normalization_preserves_sign_and_percent(self) -> None:
        self.assertEqual(_canonical_number("(3,099)"), "-3099")
        self.assertEqual(_canonical_number("$4,835"), "4835")
        self.assertEqual(_canonical_number("21.4%"), "21.4%")

    def test_spec_requires_frozen_budget_and_single_model(self) -> None:
        spec = {
            "status": "FROZEN_DEVELOPMENT_FEASIBILITY_DIAGNOSTIC",
            "frozen_before_live_run": True,
            "live_call_budget": {"maximum_model_calls": 18},
            "model_and_pipeline": {"models": ["llama3:latest"]},
        }
        _validate_spec(spec)
        spec["live_call_budget"]["maximum_model_calls"] = 19
        with self.assertRaises(ValueError):
            _validate_spec(spec)


if __name__ == "__main__":
    unittest.main()
