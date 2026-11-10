"""Milestone completion weights do not alter calendar scheduling."""
import json
import unittest

from marina_custom_apps.design_management.clean_milestones.schedule import (
    baseline_progress, milestone_plan_weights, milestone_weight_days,
)


def step(name, lead=0, *, evidence=None, mode="Manual"):
    return {
        "step": name, "enabled": 1, "transition_mode": mode,
        "responsible_module_role": "Designer", "custody_role": "Designer",
        "lead_time_days": lead, "requires_evidence": 1 if evidence else 0,
        "evidence_type": evidence,
    }


def plan(name, snapshot, state="Planned", weight=None):
    return {
        "name": name, "milestone_type": name, "sequence": 10,
        "plan_state": state, "completion_weight_days": weight,
        "workflow_snapshot_json": json.dumps(snapshot),
    }


class WeightedCompletionTests(unittest.TestCase):
    def setUp(self):
        self.tech = {"steps": [step("Completed", 0, evidence="Tech Pack", mode="Auto")]}
        self.production = {"steps": [
            step("Ready to Start", 0, mode="Auto"),
            step("In Progress", 3),
            step("Completed", 7),
        ]}

    def test_tech_pack_represents_ten_days(self):
        self.assertEqual(milestone_weight_days(self.tech), 10)
        self.assertEqual(milestone_weight_days({
            **self.tech, "completion_weight_days": 12
        }), 12)

    def test_other_zero_day_milestones_get_one_day(self):
        self.assertEqual(milestone_weight_days({
            "steps": [step("Completed", 0, evidence="Fitting Report", mode="Auto")]
        }), 1)

    def test_workflow_duration_excludes_conditional_rework(self):
        production_with_rework = {"steps": [
            step("Ready to Start", 0, mode="Auto"),
            step("In Progress", 3),
            step("Rework", 30),
            step("Completed", 7),
        ]}
        self.assertEqual(milestone_weight_days(production_with_rework), 10)

    def test_completed_parallel_milestone_earns_weight(self):
        plans = [
            plan("tech", self.tech, "Completed"),
            plan("sourcing", self.production, "Active"),
            plan("production", self.production, "Completed"),
        ]
        executions = {
            "tech": {"status": "Completed"},
            "sourcing": {"status": "In Progress"},
            "production": {"status": "Completed"},
        }
        result = baseline_progress(plans, "2026-10-31", executions)
        self.assertEqual(result, {
            "percent": 67, "earned_days": 20, "total_days": 30
        })

    def test_status_must_agree_with_plan(self):
        plans = [plan("tech", self.tech, "Completed"),
                 plan("production", self.production, "Active")]
        executions = {"tech": {"status": "In Progress"},
                      "production": {"status": "Completed"}}
        self.assertEqual(baseline_progress(plans, None, executions)["percent"], 0)

    def test_legacy_plan_reads_frozen_snapshot(self):
        plans = [plan("tech", self.tech, "Completed"),
                 plan("production", self.production)]
        self.assertEqual(milestone_plan_weights(plans),
                         {"tech": 10, "production": 10})
        self.assertEqual(baseline_progress(
            plans, "2026-10-31", {"tech": {"status": "Completed"}})["percent"], 50)

    def test_persisted_weight_outranks_snapshot(self):
        self.assertEqual(milestone_plan_weights(
            [plan("tech", self.tech, "Completed", weight=15)]), {"tech": 15})

    def test_no_false_one_hundred(self):
        plans = [plan("large", self.production, "Completed", weight=999),
                 plan("small", self.tech, "Planned", weight=1)]
        result = baseline_progress(plans, None,
                                   {"large": {"status": "Completed"}})
        self.assertEqual(result["percent"], 99)
        plans[1]["plan_state"] = "Completed"
        self.assertEqual(baseline_progress(plans, None, {
            "large": {"status": "Completed"},
            "small": {"status": "Completed"},
        })["percent"], 100)

    def test_invalid_override(self):
        for bad in (-1, 3651, 1.5, True):
            with self.assertRaises(ValueError):
                milestone_weight_days({**self.tech, "completion_weight_days": bad})


if __name__ == "__main__":
    unittest.main()
