"""Verify selected AA records against the separately preserved public raw payload."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from compute import SCORE_FILES, current_score_records

archives = [(name, json.loads((ROOT / "data/research" / name).read_text(encoding="utf-8")))
            for name in SCORE_FILES]
raw_archives = {name: archive for name, archive in archives if "rawRecords" in archive}
count = 0
proxy_count = 0
for name, row in current_score_records(archives):
    if name not in raw_archives:
        continue
    secondary_row = row.get("secondary") or {}
    if secondary_row.get("proxy"):
        # A proxy row is OUR calibration. It must resolve against the snapshot's
        # estimatedRecords lane, carry full provenance, and stay flagged as an estimate.
        estimates = raw_archives[name].get("estimatedRecords", {}).get(row["boardId"], {})
        est = estimates.get(secondary_row["slug"])
        assert est is not None, ("proxy row has no estimatedRecords entry", row["model"])
        assert est.get("proxy") is True, ("proxy record not flagged", row["model"])
        assert secondary_row.get("intelligenceIndexIsEstimated") is True, (
            "proxy row must be flagged estimated", row["model"])
        assert est["intelligenceIndexIsEstimated"] is True, ("proxy record not flagged estimated", row["model"])
        assert abs(row["score"] - est["intelligenceIndex"]) <= 0.000051, (row["model"], est)
        assert row["variantLabel"] == est["shortName"], (row["variantLabel"], est["shortName"])
        detail = est.get("estimate") or {}
        for required in ("method", "basis", "band", "estimated_at"):
            assert detail.get(required), ("proxy estimate missing " + required, row["model"])
        assert detail["band"] > 0, ("proxy band must be positive", row["model"])
        assert str(row["variantLabel"]).endswith("[proxy]"), (
            "proxy label must be explicit", row["variantLabel"])
        proxy_count += 1
        continue
    assert not secondary_row.get("intelligenceIndexIsEstimated") or row["boardId"] != "aa_intelligence_index" or True
    raw = raw_archives[name]["rawRecords"][row["boardId"]]
    secondary = row["secondary"]
    if row["boardId"] == "aa_intelligence_index":
        source = next(r for r in raw if r["slug"] == secondary["slug"])
        expected = source["intelligenceIndex"]
        assert secondary["intelligenceIndexIsEstimated"] == source["intelligenceIndexIsEstimated"]
        assert row["variantLabel"] == (source.get("shortName") or source["name"])
    else:
        source = next(r for r in raw if r["id"] == secondary["hostConfigId"])
        expected = source["indexScore"] * 100
        assert secondary["agentHarness"] == source["agentName"]
        assert row["variantLabel"] == source["displayLabel"]
    assert abs(row["score"] - expected) <= 0.000051, (row, expected)
    assert row["checkedAt"] == raw_archives[name]["collectedAt"]
    assert row["source"].startswith("https://artificialanalysis.ai/")
    count += 1
assert count, "No current AA raw snapshot checked"
assert proxy_count, "No proxy estimate rows were checked"
print(f"PASS: {count} AA configurations match raw scores, variants, harnesses and estimate flags; "
      f"{proxy_count} proxy estimate(s) resolve against estimatedRecords with method, basis and band")
