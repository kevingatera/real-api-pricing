#!/usr/bin/env python3
"""Build data/research/scores-aa-round4-2026-09-25.json from a fresh AA payload.

Why a script instead of hand-editing the snapshot: the fork's rule is that a new board
snapshot replaces that board as a whole, so a refresh must (a) carry every configuration
the new payload still reports, (b) drop nothing silently, and (c) keep every existing
score mapping consistent with the raw values - scripts/checks/verify_aa_snapshot.py
asserts score == raw intelligenceIndex for the mapped slug.

Inputs:
  data/research/scores-aa-round3-2026-09-09.json   previous snapshot (scores + rawRecords)
  /tmp/aa_payload_20260925.json                    AA model payload read 2026-09-25
Outputs:
  data/research/scores-aa-round4-2026-09-25.json
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from proxy_estimates import SAME_WEIGHTS, VENDOR_ANCHORED, UNSCORED  # noqa: E402

ROOT = Path("/tmp/rap")
RESEARCH = ROOT / "data" / "research"
PREV = RESEARCH / "scores-aa-round3-2026-09-09.json"
PAYLOAD = Path("/tmp/aa_payload_20260925.json")
OUT = RESEARCH / "scores-aa-round4-2026-09-25.json"
COLLECTED = "2026-09-25"

prev = json.loads(PREV.read_text(encoding="utf-8"))
payload = json.loads(PAYLOAD.read_text(encoding="utf-8"))

# index the previous snapshot's raw records by slug (intelligence board) and by host config id
prev_aa = {r["slug"]: r for r in prev["rawRecords"]["aa_intelligence_index"] if r.get("slug")}
payload_by_slug = {r["slug"]: r for r in payload if r.get("slug")}

# --- 1. build the new aa_intelligence_index raw board -----------------------------
# A configuration the 2026-09-25 payload still reports is taken from the payload (fresh
# values). Anything the payload no longer reports is DROPPED from the board, which is what
# "replaces the board as a whole" means, and is listed in droppedFromPayload for audit.
new_raw = []
dropped, updated = [], []
for r in payload:
    new_raw.append(r)
    slug = r.get("slug")
    old = prev_aa.get(slug)
    if old and old.get("intelligenceIndex") != r.get("intelligenceIndex"):
        updated.append({
            "slug": slug,
            "was": old["intelligenceIndex"],
            "now": r["intelligenceIndex"],
            "name": r.get("name"),
        })
for slug, old in prev_aa.items():
    if slug not in payload_by_slug:
        dropped.append({"slug": slug, "name": old.get("name"), "index": old.get("intelligenceIndex")})

# --- 2. carry the coding-agent board forward (its payload lives on a different page) ---
carried_coding = prev["rawRecords"]["aa_coding_agent_index"]

# --- 3. refresh every existing score mapping against the new raw values ------------
scores = []
stale, missing_raw = [], []
for s in prev["scores"]:
    s = json.loads(json.dumps(s))
    if s["boardId"] == "aa_intelligence_index":
        slug = s["secondary"]["slug"]
        raw = payload_by_slug.get(slug)
        if raw is None:
            missing_raw.append({"model": s["model"], "slug": slug})
            continue
        s["score"] = raw["intelligenceIndex"]
        s["variantLabel"] = raw.get("shortName") or raw.get("name") or s.get("variantLabel")
        s["secondary"]["intelligenceIndexIsEstimated"] = raw["intelligenceIndexIsEstimated"]
        s["secondary"]["scoreRoundedDisplay"] = round(raw["intelligenceIndex"])
        s["secondary"]["shortName"] = raw.get("shortName") or raw.get("name") or s["secondary"].get("shortName")
        s["checkedAt"] = COLLECTED
    else:
        s["checkedAt"] = COLLECTED
    scores.append(s)

# --- 4. add mappings for models the plans serve that AA now covers ------------------
# slug -> (plan model id, effort note). Only added when the slug is genuinely new to the
# snapshot; a model with no row in build_adopted simply produces no chart point.
ADDITIONS = {
    "deepseek-v4-1-flash": ("deepseek-v4.1-flash", "max effort"),
    "mimo-v2-6-pro": ("mimo-v2.6-pro", "default"),
    "grok-4-7": ("grok-4.7", "xhigh"),
    "gpt-6-luna": ("gpt-6-luna", "max"),
    "step-5": ("step-5-preview", "preview"),
    # Mapping GAP, not a proxy: AA carries Qwen3.8 Max (0902) under slug qwen3-8-max at
    # 45.4152, while the plan row qwen3.8-max-0902 had no mapping at all.
    "qwen3-8-max": ("qwen3.8-max-0902", "0902 snapshot"),
}
existing = {(s["model"], s["secondary"].get("slug")) for s in scores}
added = []
for slug, (model_id, effort) in ADDITIONS.items():
    raw = payload_by_slug.get(slug)
    if raw is None or (model_id, slug) in existing:
        continue
    scores.append({
        "model": model_id,
        "boardId": "aa_intelligence_index",
        "variantLabel": raw.get("shortName") or raw.get("name"),
        "score": raw["intelligenceIndex"],
        "secondary": {
            "costPerTaskUsd": (raw.get("intelligenceIndexCostPerTask") or {}).get("cost", {}).get("total")
            if isinstance(raw.get("intelligenceIndexCostPerTask"), dict) else None,
            "scoreRoundedDisplay": round(raw["intelligenceIndex"]),
            "intelligenceIndexIsEstimated": raw["intelligenceIndexIsEstimated"],
            "slug": slug,
            "shortName": raw.get("shortName") or raw.get("name"),
            "releaseDate": None,
            "isReasoning": raw.get("isReasoning"),
            "deprecated": raw.get("deprecated"),
            "modelCreatorName": raw.get("modelCreatorName"),
            "effort": effort,
        },
        "source": "https://artificialanalysis.ai/leaderboards/models",
        "checkedAt": COLLECTED,
    })
    added.append({"model": model_id, "slug": slug, "score": raw["intelligenceIndex"]})

# --- 5. proxy-estimate lane (AA has not scored these configurations) ----------------
proxy_rows, estimated_records, not_estimated = [], {}, []
for e in SAME_WEIGHTS:
    anchor = payload_by_slug.get(e["anchor"])
    assert anchor is not None, f"anchor slug missing for {e['model']}: {e['anchor']}"
    pseudo = "proxy:" + e["model"]
    record = {
        "slug": pseudo,
        "name": e["model"],
        "shortName": e["model"] + " [proxy]",
        "intelligenceIndex": anchor["intelligenceIndex"],
        "intelligenceIndexIsEstimated": True,
        "proxy": True,
        "estimate": {
            "method": "same-weights serving variant: AA score inherited from " + e["anchor"],
            "basis": e["basis"],
            "band": e["band"],
            "anchor_slugs": [e["anchor"]],
            "note": e["note"],
            "estimated_at": COLLECTED,
        },
    }
    estimated_records[pseudo] = record
    proxy_rows.append((e["model"], pseudo, record))

for e in VENDOR_ANCHORED:
    pseudo = "proxy:" + e["model"]
    record = {
        "slug": pseudo,
        "name": e["model"],
        "shortName": e["model"] + " [proxy]",
        "intelligenceIndex": e["value"],
        "intelligenceIndexIsEstimated": True,
        "proxy": True,
        "estimate": {
            "method": e["method"],
            "basis": e["basis"],
            "band": e["band"],
            "anchor_slugs": e["anchor"],
            "note": e["note"],
            "estimated_at": COLLECTED,
        },
    }
    estimated_records[pseudo] = record
    proxy_rows.append((e["model"], pseudo, record))

for e in UNSCORED:
    not_estimated.append({"model": e["model"], "reason": e["reason"]})

for model, pseudo, record in proxy_rows:
    scores.append({
        "model": model,
        "boardId": "aa_intelligence_index",
        "variantLabel": record["name"] + " [proxy]",
        "score": record["intelligenceIndex"],
        "estimated": True,
        "secondary": {
            "scoreRoundedDisplay": round(record["intelligenceIndex"]),
            "intelligenceIndexIsEstimated": True,
            "proxy": True,
            "slug": pseudo,
            "shortName": record["name"] + " [proxy]",
            "releaseDate": None,
            "isReasoning": None,
            "deprecated": False,
            "modelCreatorName": None,
            "effort": None,
            "estimate": record["estimate"],
        },
        "source": "proxy: see estimate.basis",
        "checkedAt": COLLECTED,
    })

out = {
    "collectedAt": COLLECTED,
    "revises": PREV.name,
    "revisionNote": (
        "Complete Artificial Analysis board refresh from the payload read 2026-09-25 "
        f"({len(payload)} configurations). The intelligence board is replaced as a whole: "
        f"{len(updated)} configurations carry revised scores, {len(added)} new configuration(s) "
        f"were added, and {len(dropped)} slug(s) the payload no longer reports were dropped from "
        "this board. The coding-agent board is carried forward from round3 unchanged (its payload "
        "lives on the coding-agents page and was not re-read in this round)."
    ),
    "extraction": {
        "method": "read the model payload embedded in artificialanalysis.ai/leaderboards/models",
        "readAt": COLLECTED,
        "configurations": len(payload),
        "note": "same field set the round3 rawRecords carry (slug, name, shortName, "
                "intelligenceIndex, intelligenceIndexIsEstimated, creator, prices, benchmarks)",
    },
    "boards": [
        {
            "boardId": "aa_intelligence_index",
            "name": "Artificial Analysis Intelligence Index v4.3.2",
            "url": "https://artificialanalysis.ai/leaderboards/models",
            "metric": "Intelligence Index",
            "snapshotDate": COLLECTED,
            "note": "Read 2026-09-25 from the public HTML RSC embedded model payload (the same "
                    "method round3 documents); the page UI rounds to integers, the payload "
                    "carries full precision. The page now labels the index v4.3.2 rather than "
                    "v4.3; the methodology string lists 10 evaluations "
                    "(AA-Briefcase v1.1, GDPval-AA v2.1, AutomationBench-AA, Terminal-Bench 4.0, "
                    "SciCode, HLE, GDP.pdf, CritPt, ...). 673 configurations, up from 633 in "
                    "round3; 136 configurations carry revised scores, 2 mappings added, "
                    "4 configurations the payload no longer reports were dropped from the board.",
        },
        {
            "boardId": "aa_coding_agent_index",
            "name": "Artificial Analysis Coding Agent Index v1.4",
            "url": "https://artificialanalysis.ai/agents/coding-agents",
            "metric": "Coding Agent Index",
            "snapshotDate": "2026-09-09",
            "note": "Carried forward from scores-aa-round3-2026-09-09.json, NOT re-read in this "
                    "round: the coding-agent board comes from a different page "
                    "(https://artificialanalysis.ai/agents/coding-agents). Equal-weight mean of "
                    "DeepSWE, Terminal-Bench v2.1, SWE-Atlas-QnA, v1.4, 68 configurations. "
                    "Refreshing it is a separate round.",
        },
    ],
    "scores": scores,
    "rawRecords": {
        "aa_intelligence_index": new_raw,
        "aa_coding_agent_index": carried_coding,
        "note": "aa_intelligence_index replaced from the 2026-09-25 payload; "
                "aa_coding_agent_index carried forward from round3",
    },
    "updates": updated,
    "additions": added,
    "droppedFromPayload": dropped,
    "scoreMappingsWithoutRaw": missing_raw,
    "estimatedRecords": {"aa_intelligence_index": estimated_records},
    "estimatedRows": [m for m, _, _ in proxy_rows],
    "notEstimated": not_estimated,
    "carriedForward": {"aa_coding_agent_index": PREV.name},
}

OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"wrote {OUT.name}")
print(f"  configurations in payload: {len(payload)} (round3 had {len(prev_aa)})")
print(f"  revised scores: {len(updated)}")
print(f"  new score mappings added: {len(added)} -> {added}")
print(f"  dropped (not in payload): {len(dropped)} -> {[d['slug'] for d in dropped][:10]}")
print(f"  mappings whose slug vanished: {len(missing_raw)} -> {missing_raw[:5]}")
print(f"  proxy estimates written: {len(proxy_rows)} -> {[m for m, _, _ in proxy_rows]}")
print(f"  deliberately unscored: {[e['model'] for e in not_estimated]}")
print("  sample revisions:")
for u in updated[:8]:
    print(f"    {u['slug']}: {u['was']:.4f} -> {u['now']:.4f}")
