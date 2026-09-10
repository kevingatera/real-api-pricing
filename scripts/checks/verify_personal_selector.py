#!/usr/bin/env python3
"""Regression checks for the personal subscription selector."""

from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("select_personal_pareto", ROOT / "scripts" / "select_personal_pareto.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


def fixture():
    points = {"points": [
        {"id": "opencode_go::deepseek-v4-flash", "plan": "OpenCode Go", "monthly_yi": 21.637,
         "real_usd_per_mtok": 0.00462, "aa_intelligence_index__score": 34.5},
        {"id": "opencode_go::glm-5.3-flash", "plan": "OpenCode Go", "monthly_yi": 4.383,
         "real_usd_per_mtok": 0.02282, "aa_intelligence_index__score": 41.9},
        {"id": "opencode_go::mimo-v2.5", "plan": "OpenCode Go", "monthly_yi": 89.286,
         "real_usd_per_mtok": 0.00112, "aa_intelligence_index__score": 22.3},
        {"id": "command_code_goat::deepseek-v4-flash", "plan": "Command Code GOAT", "monthly_yi": 43.274,
         "real_usd_per_mtok": 0.00231, "aa_intelligence_index__score": 34.5},
    ]}
    policy = {"models": {
        "deepseek-v4-flash": {"context_tokens": 1_000_000, "served_version_date": "2026-07-31",
                              "use_cases": {"compression": {"approved": True}}},
        "glm-5.3-flash": {"context_tokens": 1_000_000, "served_version_date": "2026-09-09",
                          "use_cases": {"compression": {"approved": True}}},
        "mimo-v2.5": {"context_tokens": 1_000_000, "served_version_date": "2026-05-28",
                      "use_cases": {"compression": {"approved": False}}},
    }}
    profile = {
        "as_of": "2026-09-09", "use_case": "compression",
        "plans": ["opencode_go", "command_code_goat"],
        "constraints": {
            "min_context_tokens": 1_000_000, "max_model_age_days": 90, "require_zdr": True,
            "max_zdr_evidence_age_days": 35, "require_known_capacity": True,
            "quality_board": "aa_intelligence_index", "min_quality_score": 30,
        },
        "selection": {"strategy": "capacity_after_quality_floor"},
    }
    runtime = {"routes": [
        {"plan_id": "opencode_go", "provider": "opencode-go", "model": "deepseek-v4-flash",
         "provider_model": "deepseek-v4-flash", "live": True, "zdr": True, "zdr_verified_at": "2026-09-09",
         "zdr_valid_through": "2026-09-30", "capacity_known": True, "plan_verified": True},
        {"plan_id": "opencode_go", "provider": "opencode-go", "model": "glm-5.3-flash",
         "provider_model": "glm-5.3-flash", "live": True, "zdr": True, "zdr_verified_at": "2026-09-09",
         "capacity_known": True, "plan_verified": True},
        {"plan_id": "opencode_go", "provider": "opencode-go", "model": "mimo-v2.5",
         "provider_model": "mimo-v2.5", "live": True, "zdr": True, "zdr_verified_at": "2026-09-09",
         "capacity_known": True, "plan_verified": True},
        {"plan_id": "command_code_goat", "provider": "commandcode-zdr", "model": "deepseek-v4-flash",
         "provider_model": "deepseek/deepseek-v4-flash", "live": True, "zdr": True,
         "zdr_verified_at": "2026-09-09", "capacity_known": False, "plan_verified": False},
    ]}
    return points, policy, profile, runtime


def main() -> None:
    report = MODULE.evaluate(*fixture())
    assert report["selected"]["id"] == "opencode_go::deepseek-v4-flash"
    assert {row["model"] for row in report["frontier"]} == {"deepseek-v4-flash", "glm-5.3-flash"}
    by_id = {row["id"]: row for row in report["candidates"]}
    assert set(by_id["opencode_go::mimo-v2.5"]["reasons"]) >= {
        "use_case_not_reviewed", "model_too_old", "quality_below_floor"
    }
    assert by_id["command_code_goat::deepseek-v4-flash"]["reasons"] == [
        "plan_identity_unverified", "zdr_capacity_unknown"
    ]

    points, policy, profile, runtime = fixture()
    runtime["routes"][0]["zdr_valid_through"] = "2026-09-08"
    expired = MODULE.evaluate(points, policy, profile, runtime)
    deepseek = next(row for row in expired["candidates"] if row["id"] == "opencode_go::deepseek-v4-flash")
    assert "zdr_agreement_expired" in deepseek["reasons"]
    assert expired["selected"]["id"] == "opencode_go::glm-5.3-flash"
    print("personal selector checks passed")


if __name__ == "__main__":
    main()
