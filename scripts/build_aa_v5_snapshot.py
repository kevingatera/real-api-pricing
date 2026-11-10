#!/usr/bin/env python3
"""Build an AA Intelligence Index v5 snapshot from a compact payload.

Intelligence Index v5 rescales every score, so v5 values cannot join the v4.3.2 board. As at
the v4.3 change, a v5 snapshot replaces the intelligence board as a whole. Rules:

  1. Measured. A plan model with at least one AA-measured v5 configuration keeps only its
     measured configurations. Estimates never compete with a measurement of the same model.
  2. Component reconstruction (aa_v5_reconstruct.py). A plan model with no measured
     configuration gets one proxy row per configuration AA ran at least four of the nine v5
     evaluations on. The band is that configuration's measured leave-one-out p90 error.
  3. Same-weights and vendor-anchored proxies (proxy_estimates.py), re-derived on the v5 scale.
     A same-weights proxy on a reconstructed anchor adds the anchor's band to its own.
  4. Anything else is listed in notEstimated with its reason and has no AA point.

The plan-to-configuration map is kept in the snapshot ("configurationMap") so a later build
repeats the same choices. On the first v5 build it comes from the v4.3.2 snapshot's rows. A new
mapping is a human decision: add it to MAP_ADDITIONS. The coding-agent board is carried forward.

With --if-changed, nothing is written when every AA row (ignoring dates), the configuration map
and the not-estimated list match the prior v5 snapshot. The build refuses a payload that lost a
mapped configuration or one of its evaluations since the prior v5 snapshot. --summary writes a JSON description of the build for the weekly job.

Usage:
  python scripts/build_aa_v5_snapshot.py --payload _build/aa-v5/payload.json --date 2026-11-09
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "data" / "research"
sys.path.insert(0, str(ROOT / "scripts"))
from aa_v5_reconstruct import COMPONENTS, MIN_PRESENT, Reconstructor, number  # noqa: E402
from compute import SCORE_FILES  # noqa: E402
from proxy_estimates import SAME_WEIGHTS, UNSCORED, VENDOR_ANCHORED, VENDOR_ANCHORED_V5  # noqa: E402

BOARD = "aa_intelligence_index"
CODING_BOARD = "aa_coding_agent_index"
SOURCE = "https://artificialanalysis.ai/models/{}"
# Human-approved mappings added after the first v5 build: {"plan-model-id": [("aa-slug", "effort")]}.
MAP_ADDITIONS: dict[str, list[tuple[str, str | None]]] = {}


def prior_snapshot() -> tuple[str, dict]:
    for name in reversed(SCORE_FILES):
        archive = json.loads((RESEARCH / name).read_text(encoding="utf-8"))
        if BOARD in archive.get("rawRecords", {}):
            return name, archive
    raise SystemExit("no registered snapshot carries the AA intelligence board")


def configuration_map(prior: dict) -> list[dict]:
    if "configurationMap" in prior:
        entries = [dict(e) for e in prior["configurationMap"]]
    else:
        entries = [{"model": r["model"], "slug": r["secondary"]["slug"], "effort": r["secondary"].get("effort")}
                   for r in prior["scores"] if r["boardId"] == BOARD and not r["secondary"].get("proxy")]
    for model, pairs in MAP_ADDITIONS.items():
        entries += [{"model": model, "slug": slug, "effort": effort} for slug, effort in pairs]
    seen, out = set(), []
    for e in entries:
        if (e["model"], e["slug"]) not in seen:
            seen.add((e["model"], e["slug"]))
            out.append(e)
    return sorted(out, key=lambda e: (e["model"], e["slug"]))


def check_payload(prior: dict, records: dict, mapping: list, version: str) -> None:
    """Refuse a payload that lost a mapped configuration or one of its evaluations since the prior v5 build.

    A timeout or page-layout change in the fetch looks the same as AA dropping data. Either way a
    person should look before scores disappear from the board.
    """
    prior_version = next(b["name"] for b in prior["boards"] if b["boardId"] == BOARD).rsplit("v", 1)[-1]
    if prior_version.split(".")[0] != version.split(".")[0]:
        return
    before = {r["slug"]: r for r in prior["rawRecords"][BOARD]}
    problems = []
    for slug in sorted({e["slug"] for e in mapping} & set(before)):
        if slug not in records:
            problems.append(f"{slug}: no record in this payload")
            continue
        lost = sorted(set(before[slug].get("benchmarks", {})) - set(records[slug].get("benchmarks", {})))
        if lost:
            problems.append(f"{slug}: lost {', '.join(lost)}")
        if number(before[slug].get("intelligenceIndex")) is not None and number(records[slug].get("intelligenceIndex")) is None:
            problems.append(f"{slug}: lost its v5 score")
    if problems:
        raise SystemExit("payload is missing data the prior v5 snapshot had; check the fetch before rebuilding:\n  "
                         + "\n  ".join(problems))


def label(record: dict) -> str:
    return record.get("shortName") or record.get("name")


def row(model: str, record: dict, effort, date: str, proxy: bool) -> dict:
    out = {
        "model": model,
        "boardId": BOARD,
        "variantLabel": record["shortName"] if proxy else label(record),
        "score": record["intelligenceIndex"],
        "secondary": {
            "scoreRoundedDisplay": round(record["intelligenceIndex"]),
            "intelligenceIndexIsEstimated": True if proxy else record.get("intelligenceIndexIsEstimated"),
            "slug": record["slug"],
            "shortName": record["shortName"] if proxy else label(record),
            "releaseDate": None,
            "isReasoning": record.get("isReasoning"),
            "deprecated": False if proxy else record.get("deprecated"),
            "modelCreatorName": record.get("modelCreatorName"),
            "effort": effort,
        },
        "source": "proxy: see estimate.basis" if proxy else SOURCE.format(record["slug"]),
        "checkedAt": date,
    }
    if proxy:
        out["estimated"] = True
        out["secondary"]["proxy"] = True
        out["secondary"]["estimate"] = record["estimate"]
    return out


def proxy_record(pseudo: str, name: str, value: float, estimate: dict) -> dict:
    return {"slug": pseudo, "name": name, "shortName": name + " [proxy]", "intelligenceIndex": round(value, 4),
            "intelligenceIndexIsEstimated": True, "proxy": True, "estimate": estimate}


def build(payload: dict, date: str) -> tuple[str, dict, dict]:
    version = payload.get("indexVersion") or ""
    if not version.startswith("5"):
        raise SystemExit(f"payload index version is {version!r}; this builder is for v5")
    records = {r["slug"]: r for r in payload["records"]}
    prior_name, prior = prior_snapshot()
    recon = Reconstructor(payload["records"])
    mapping = configuration_map(prior)
    check_payload(prior, records, mapping, version)

    by_model: dict[str, list[dict]] = {}
    for e in mapping:
        by_model.setdefault(e["model"], []).append(e)

    scores, estimated, not_estimated, set_aside = [], {}, [], []
    reconstructions: dict[str, dict | None] = {}

    def reconstruct(slug: str) -> dict | None:
        if slug not in reconstructions:
            reconstructions[slug] = recon.reconstruct(records[slug]) if slug in records else None
        return reconstructions[slug]

    for model, entries in sorted(by_model.items()):
        measured = [e for e in entries if number(records.get(e["slug"], {}).get("intelligenceIndex")) is not None]
        if measured:
            scores += [row(model, records[e["slug"]], e["effort"], date, proxy=False) for e in measured]
            set_aside += [{"model": model, "slug": e["slug"],
                           "reason": "no v5 score; the plan model has a measured v5 configuration"}
                          for e in entries if e not in measured]
            continue
        made = 0
        for e in entries:
            slug = e["slug"]
            result = reconstruct(slug)
            if result is None:
                present = len(records.get(slug, {}).get("benchmarks", {}).keys() & set(COMPONENTS))
                set_aside.append({"model": model, "slug": slug,
                                  "reason": (f"no v5 score; {present} of 9 v5 evaluations measured, reconstruction "
                                             f"needs {MIN_PRESENT}") if slug in records else "AA has no record"})
                continue
            record = proxy_record("proxy:" + slug, label(records[slug]), result["value"], {
                "method": "v5 component reconstruction: missing v5 evaluations imputed from this configuration's "
                          f"AA benchmarks, then the v5 combination fitted on {len(recon.train)} AA-scored "
                          f"configurations (R2 {recon.r2:.4f}) applied",
                "basis": [SOURCE.format(slug), "scripts/aa_v5_reconstruct.py"],
                "band": round(result["band"], 2),
                "median_error": round(result["median_error"], 2),
                "validated_on": result["validated_on"],
                "anchor_slugs": [slug],
                "measured_components": result["measured_components"],
                "imputed_components": result["imputed_components"],
                "estimated_at": date,
            })
            estimated[record["slug"]] = record
            scores.append(row(model, record, e["effort"], date, proxy=True))
            made += 1
        if not made:
            not_estimated.append({"model": model, "reason": "AA has no v5 score and too few v5 evaluations for "
                                                            "any mapped configuration"})

    covered = {r["model"] for r in scores}
    for e in SAME_WEIGHTS:
        if e["model"] in covered:
            continue
        anchor = records.get(e["anchor"], {})
        value, band, how = None, e["band"], None
        if number(anchor.get("intelligenceIndex")) is not None:
            value, how = anchor["intelligenceIndex"], "AA-measured v5 score"
        elif (result := reconstruct(e["anchor"])) is not None:
            value, band, how = result["value"], e["band"] + result["band"], "v5 component reconstruction"
        if value is None:
            not_estimated.append({"model": e["model"], "reason": f"same-weights anchor {e['anchor']} has no v5 score "
                                                                 "and cannot be reconstructed"})
            continue
        record = proxy_record("proxy:" + e["model"], e["model"], value, {
            "method": f"same-weights serving variant: inherits the {how} of {e['anchor']}",
            "basis": e["basis"], "band": round(band, 2), "anchor_slugs": [e["anchor"]],
            "note": e["note"], "estimated_at": date})
        estimated[record["slug"]] = record
        scores.append(row(e["model"], record, None, date, proxy=True))

    v5_vendor = {e["model"] for e in VENDOR_ANCHORED_V5}
    covered = {r["model"] for r in scores}
    for e in VENDOR_ANCHORED_V5:
        if e["model"] in covered:
            continue
        record = proxy_record("proxy:" + e["model"], e["model"], e["value"], {
            "method": e["method"], "basis": e["basis"], "band": e["band"], "anchor_slugs": e["anchor"],
            "note": e["note"], "estimated_at": date})
        estimated[record["slug"]] = record
        scores.append(row(e["model"], record, None, date, proxy=True))
    not_estimated += [{"model": e["model"], "reason": "the v4.3.2 vendor-anchored estimate has no v5 equivalent; "
                                                      "see proxy_estimates.VENDOR_ANCHORED_V5"}
                      for e in VENDOR_ANCHORED if e["model"] not in v5_vendor]
    not_estimated += [{"model": e["model"], "reason": e["reason"]} for e in UNSCORED]
    scored, seen = {r["model"] for r in scores}, set()
    not_estimated = [e for e in not_estimated
                     if e["model"] not in scored and not (e["model"] in seen or seen.add(e["model"]))]

    coding_rows = [r for r in prior["scores"] if r["boardId"] == CODING_BOARD]
    measured_count = sum(1 for r in scores if not r["secondary"].get("proxy"))
    proxy_count = len(scores) - measured_count
    name = f"scores-aa-v5-{date}.json"
    out = {
        "collectedAt": date,
        "revises": prior_name,
        "carriedDates": sorted({r["checkedAt"] for r in coding_rows} - {date}),
        "revisionNote": (
            f"Artificial Analysis Intelligence Index v{version} board read on {payload['readAt']}. v5 is not on the "
            f"v4.3.2 scale, so the intelligence board is replaced as a whole. {measured_count} plan configuration(s) "
            f"carry an AA-measured v5 score and {proxy_count} carry a labelled proxy estimate. The coding-agent "
            "board is carried forward unchanged."
        ),
        "extraction": {
            "method": "leaderboard initialModels payload plus each mapped configuration's model page "
                      "(scripts/fetch_aa_v5_payload.py)",
            "readAt": payload["readAt"],
            "configurations": len(records),
            "leaderboardConfigurations": payload["leaderboardConfigurations"],
            "modelPagesRead": payload["modelPagesRead"],
        },
        "boards": [
            {
                "boardId": BOARD,
                "name": f"Artificial Analysis Intelligence Index v{version}",
                "url": "https://artificialanalysis.ai/leaderboards/models",
                "metric": "Intelligence Index",
                "snapshotDate": date,
                "note": ("Intelligence Index v5 combines nine evaluations: AA-Briefcase, AutomationBench-AA, "
                         "Terminal-Bench 4.0, FrontierCode 2.0, Omniscience, GDP.pdf, HLE Diamond, CritPt v2 Hard "
                         "and Terminal-Bench Science. Scores are not comparable with v4.3.2; a lower number is not "
                         "a regression. This board replaces the v4.3.2 board as a whole."),
            },
            next(b for b in prior["boards"] if b["boardId"] == CODING_BOARD),
        ],
        "scores": scores + coding_rows,
        "rawRecords": {
            BOARD: payload["records"],
            CODING_BOARD: prior["rawRecords"][CODING_BOARD],
            "note": f"{BOARD} read on {payload['readAt']} (index v{version}); {CODING_BOARD} carried forward "
                    f"from {prior.get('carriedForward', {}).get(CODING_BOARD, prior_name)}",
        },
        "configurationMap": mapping,
        "reconstruction": {
            "components": list(COMPONENTS),
            "minimumMeasuredComponents": MIN_PRESENT,
            "trainedOn": len(recon.train),
            "combinationR2": round(recon.r2, 5),
            "combinationMaxError": round(recon.max_error, 3),
        },
        "configurationsSetAside": set_aside,
        "estimatedRecords": {BOARD: estimated},
        "estimatedRows": sorted({r["model"] for r in scores if r["secondary"].get("proxy")}),
        "notEstimated": not_estimated,
        "carriedForward": {CODING_BOARD: prior.get("carriedForward", {}).get(CODING_BOARD, prior_name)},
    }
    return name, out, summarize(prior_name, prior, out, records, mapping, version)


def semantic(r: dict) -> str:
    """A row without its observation dates, for deciding whether a rebuild changed anything."""
    r = json.loads(json.dumps(r))
    r.pop("checkedAt", None)
    r["secondary"].get("estimate", {}).pop("estimated_at", None)
    return json.dumps(r, sort_keys=True)


def summarize(prior_name: str, prior: dict, out: dict, records: dict, mapping: list, version: str) -> dict:
    def keyed(archive):
        return {(r["model"], r["secondary"]["slug"].removeprefix("proxy:")): r for r in archive["scores"]
                if r["boardId"] == BOARD}
    before, after = keyed(prior), keyed(out)
    prior_version = next(b["name"] for b in prior["boards"] if b["boardId"] == BOARD).rsplit("v", 1)[-1]
    moved = [{"model": k[0], "slug": k[1], "was": before[k]["score"], "now": r["score"],
              "proxy": bool(r["secondary"].get("proxy")), "wasProxy": bool(before[k]["secondary"].get("proxy"))}
             for k, r in after.items() if k in before and abs(before[k]["score"] - r["score"]) > 1e-6]
    mapped = {e["slug"] for e in mapping}
    unmapped_new = sorted((r["slug"], label(r), r["intelligenceIndex"]) for r in records.values()
                          if number(r.get("intelligenceIndex")) is not None and r["slug"] not in mapped
                          and r["slug"] not in {x["slug"] for x in prior["rawRecords"][BOARD]})
    same_version = prior_version.split(".")[0] == version.split(".")[0]
    changed = (not same_version or {k: semantic(r) for k, r in before.items()} != {k: semantic(r) for k, r in after.items()}
               or prior.get("configurationMap") != out["configurationMap"]
               or prior.get("notEstimated") != out["notEstimated"])
    return {
        "changed": changed,
        "date": out["collectedAt"],
        "prior": prior_name,
        "priorVersion": prior_version,
        "version": version,
        "measured": sum(1 for r in after.values() if not r["secondary"].get("proxy")),
        "proxy": sum(1 for r in after.values() if r["secondary"].get("proxy")),
        "moved": moved,
        "newlyMeasured": sorted(k[1] for k, r in after.items()
                                if not r["secondary"].get("proxy") and k in before and before[k]["secondary"].get("proxy")),
        "added": sorted(f"{k[0]} ({k[1]})" for k in set(after) - set(before)),
        "removed": sorted(f"{k[0]} ({k[1]})" for k in set(before) - set(after)),
        "notEstimated": [e["model"] for e in out["notEstimated"]],
        "unmappedNew": [{"slug": s, "name": n, "intelligenceIndex": v} for s, n, v in unmapped_new],
    }


def register(name: str) -> None:
    path = ROOT / "scripts" / "compute.py"
    text = path.read_text(encoding="utf-8")
    if f'"{name}"' in text:
        return
    start = text.index("SCORE_FILES = (")
    end = text.index(")", start)
    path.write_text(text[:end] + f'    "{name}",\n' + text[end:], encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--payload", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--if-changed", action="store_true", help="write nothing when the AA rows are unchanged")
    parser.add_argument("--summary", help="write a JSON summary of the build here")
    args = parser.parse_args()

    payload = json.loads(Path(args.payload).read_text(encoding="utf-8"))
    name, out, summary = build(payload, args.date)
    if args.if_changed and not summary["changed"]:
        print("AA v5 board unchanged; nothing written")
    else:
        summary["file"] = name
        (RESEARCH / name).write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        register(name)
        print(f"wrote {name}: {summary['measured']} measured, {summary['proxy']} proxy, "
              f"{len(out['configurationsSetAside'])} configuration(s) set aside, "
              f"{len(out['notEstimated'])} model(s) not estimated")
        for e in out["notEstimated"]:
            print(f"  not estimated: {e['model']}: {e['reason']}")
    if args.summary:
        Path(args.summary).write_text(json.dumps(summary, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
