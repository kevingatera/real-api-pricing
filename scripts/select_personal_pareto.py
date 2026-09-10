#!/usr/bin/env python3
"""Select a personal Pareto model after hard runtime, privacy, and freshness gates."""

from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_POINTS = ROOT / "derived" / "points.json"
DEFAULT_POLICY = ROOT / "data" / "model-policy.json"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_day(value: str) -> date:
    return date.fromisoformat(value)


def pareto_frontier(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return points not dominated on both usable capacity and quality."""
    frontier = []
    for row in rows:
        dominated = any(
            other["monthly_yi"] >= row["monthly_yi"]
            and other["quality_score"] >= row["quality_score"]
            and (other["monthly_yi"] > row["monthly_yi"] or other["quality_score"] > row["quality_score"])
            for other in rows
            if other is not row
        )
        if not dominated:
            frontier.append(row)
    return sorted(frontier, key=lambda row: (-row["monthly_yi"], -row["quality_score"]))


def evaluate(points_payload: dict[str, Any], model_policy: dict[str, Any], profile: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    as_of_value = profile.get("as_of") or runtime.get("checked_at") or date.today().isoformat()
    as_of = parse_day(as_of_value)
    constraints = profile["constraints"]
    plan_ids = set(profile["plans"])
    board = constraints["quality_board"]
    route_index = {(row["plan_id"], row["model"]): row for row in runtime.get("routes", []) if row.get("plan_id") in plan_ids}
    candidates = []
    for point in points_payload["points"]:
        plan_id, model = point["id"].split("::", 1)
        if plan_id not in plan_ids:
            continue
        route = route_index.get((plan_id, model))
        metadata = model_policy.get("models", {}).get(model)
        reasons = []
        if route is None:
            reasons.append("route_not_observed")
        elif not route.get("live"):
            reasons.append("route_not_live")
        elif not route.get("plan_verified", False):
            reasons.append("plan_identity_unverified")
        if metadata is None:
            reasons.append("freshness_not_reviewed")
            age_days = None
        else:
            age_days = (as_of - parse_day(metadata["served_version_date"])).days
            if age_days < 0:
                reasons.append("served_version_date_in_future")
            elif age_days > constraints["max_model_age_days"]:
                reasons.append("model_too_old")
            if metadata["context_tokens"] < constraints["min_context_tokens"]:
                reasons.append("context_too_small")
        if constraints.get("require_zdr") and route is not None:
            if not route.get("zdr"):
                reasons.append("zdr_not_verified")
            elif not route.get("zdr_verified_at"):
                reasons.append("zdr_evidence_undated")
            else:
                evidence_age = (as_of - parse_day(route["zdr_verified_at"])).days
                if evidence_age < 0 or evidence_age > constraints["max_zdr_evidence_age_days"]:
                    reasons.append("zdr_evidence_stale")
            valid_through = route.get("zdr_valid_through")
            if valid_through and parse_day(valid_through) < as_of:
                reasons.append("zdr_agreement_expired")
        if constraints.get("require_known_capacity") and route is not None and not route.get("capacity_known"):
            reasons.append("zdr_capacity_unknown")
        quality = point.get(f"{board}__score")
        if quality is None:
            reasons.append("quality_unscored")
        elif quality < constraints["min_quality_score"]:
            reasons.append("quality_below_floor")
        monthly_yi = point.get("monthly_yi")
        if monthly_yi is None:
            reasons.append("capacity_unavailable")
        candidates.append({
            "id": point["id"], "plan": point["plan"], "plan_id": plan_id,
            "provider": route.get("provider") if route else None,
            "model": model, "provider_model": route.get("provider_model") if route else None,
            "monthly_yi": monthly_yi, "real_usd_per_mtok": point.get("real_usd_per_mtok"),
            "quality_board": board, "quality_score": quality,
            "context_tokens": metadata.get("context_tokens") if metadata else None,
            "served_version_date": metadata.get("served_version_date") if metadata else None,
            "model_age_days": age_days, "eligible": not reasons, "reasons": reasons,
        })

    eligible = [row for row in candidates if row["eligible"]]
    frontier = pareto_frontier(eligible)
    strategy = profile.get("selection", {}).get("strategy", "capacity_after_quality_floor")
    if strategy != "capacity_after_quality_floor":
        raise ValueError(f"unsupported selection strategy: {strategy}")
    selected = max(eligible, key=lambda row: (row["monthly_yi"], row["quality_score"]), default=None)
    return {
        "as_of": as_of_value, "use_case": profile.get("use_case"),
        "policy": {
            "hard_gates": [
                "configured plan and live route", f"context >= {constraints['min_context_tokens']}",
                f"served model age <= {constraints['max_model_age_days']} days",
                "current ZDR evidence" if constraints.get("require_zdr") else "ZDR not required",
                f"{board} score >= {constraints['min_quality_score']}", "comparable capacity evidence",
            ],
            "selection": strategy,
        },
        "selected": selected, "frontier": frontier,
        "candidates": sorted(candidates, key=lambda row: (not row["eligible"], -(row["monthly_yi"] or 0))),
    }


def concise(report: dict[str, Any]) -> str:
    selected = report["selected"]
    if not selected:
        return "No model passed every hard gate. Existing routing should remain unchanged."
    frontier = ", ".join(f"{row['provider']}/{row['provider_model']}" for row in report["frontier"])
    return (
        f"Select {selected['provider']}/{selected['provider_model']} for {report['use_case']}. "
        f"It provides {selected['monthly_yi']:.3f} x 100M estimated monthly tokens at quality "
        f"{selected['quality_score']}. Pareto frontier: {frontier}."
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--points", type=Path, default=DEFAULT_POINTS)
    parser.add_argument("--model-policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = evaluate(read_json(args.points), read_json(args.model_policy), read_json(args.profile), read_json(args.runtime))
    print(json.dumps(report, indent=2, sort_keys=True) if args.json else concise(report))
    return 0 if report["selected"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
