#!/usr/bin/env python3
"""Read AA Intelligence Index v5 records into one compact JSON payload.

The models leaderboard embeds only the configurations AA currently features (285 on
2026-11-09). Plan rows map many configurations it no longer embeds, so each of those is read
from its own model page. Both sources are reduced to the same compact record: identity,
prices, flags and a "benchmarks" map keyed by AA evaluation slug. That map is what
aa_v5_reconstruct.py needs, so a snapshot built from this payload is self-contained.

Usage:
  python scripts/fetch_aa_v5_payload.py --out _build/aa-v5/payload.json [--slugs extra-slug ...]

The slugs read from model pages are every AA slug the persisted configuration map (plus
MAP_ADDITIONS) and older measured snapshots name, every proxy anchor in proxy_estimates.py,
and any --slugs given. Requests are sequential with a one-second pause. A page that cannot be
read after three tries fails the run rather than producing a payload with a gap; a 404 is
recorded in modelPagesWithoutRecord.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from compute import SCORE_FILES  # noqa: E402
from proxy_estimates import SAME_WEIGHTS  # noqa: E402
from build_aa_v5_snapshot import configuration_map, prior_snapshot  # noqa: E402

LEADERBOARD = "https://artificialanalysis.ai/leaderboards/models"
MODEL_PAGE = "https://artificialanalysis.ai/models/{}"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) real-api-pricing/1.0"
PUSH_RE = re.compile(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)')
VERSION_RE = re.compile(r"Intelligence Index v(\d+(?:\.\d+)*)")
DECODER = json.JSONDecoder()

# Model-page field -> AA evaluation slug (the leaderboard's "scores" keys). Matched by value
# on configurations present in both sources on 2026-11-09.
PAGE_FIELDS = {
    "automationBenchPartialScore": "automationbench-aa", "terminalBench40": "terminalbench-4-0",
    "frontierCode20": "frontiercode-2-0", "omniscience": "omniscience", "gdpPdfAllPass": "gdp-pdf",
    "hleDiamond": "hle-diamond", "critptAgenticHard": "critpt-v2-hard", "terminalBenchScience": "terminal-bench-science",
    "analystAgent": "aa-analyst-agent", "apexAgents": "apex-agents-aa",
    "lcr": "artificial-analysis-long-context-reasoning", "critpt": "critpt", "enterpriseOpsGym": "enterprise-ops-gym-aa",
    "frontierCode": "frontiercode", "gdpval": "gdpval-aa-normalized", "gpqa": "gpqa-diamond",
    "hle": "humanitys-last-exam", "ifbench": "ifbench", "mlcrOverall": "mlcr-aa", "mmmuPro": "mmmu-pro",
    "scicode": "scicode", "tau2": "tau2-bench", "tauBanking": "tau3-banking", "terminalBench21": "terminalbench-2-1",
    "terminalbenchHard": "terminalbench-hard",
}
IDENTITY = ("slug", "name", "shortName", "intelligenceIndex", "intelligenceIndexIsEstimated", "isReasoning",
            "isOpenWeights", "deprecated", "modelCreatorName", "price1mInputTokens", "price1mOutputTokens",
            "cacheHitPrice", "contextWindowTokens")


def number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def read(url: str) -> tuple[str, str]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    with urllib.request.urlopen(request, timeout=90) as response:
        html = response.read().decode("utf-8", errors="replace")
    body = "".join(json.loads('"' + piece + '"') for piece in PUSH_RE.findall(html))
    return html, body


def version_of(html: str) -> str | None:
    found = VERSION_RE.findall(html)
    return max(found, key=lambda v: tuple(int(p) for p in v.split("."))) if found else None


def leaderboard_record(m: dict) -> dict:
    benchmarks = {k: v for k, v in (m.get("scores") or {}).items() if number(v) is not None}
    if number(m.get("omniscience")) is not None:
        benchmarks["omniscience"] = m["omniscience"]
    record = {k: m.get(k) for k in IDENTITY}
    record.update({"modelCreatorName": m.get("modelCreatorName"), "benchmarks": benchmarks, "readFrom": "leaderboard"})
    return record


def page_record(body: str, slug: str) -> dict | None:
    """Pick the richest object on the page whose own slug is slug, and reduce it."""
    best = None
    for match in re.finditer(r'"slug":"%s"' % re.escape(slug), body):
        depth, i = 0, match.start()
        while i > 0:
            i -= 1
            if body[i] == "}":
                depth += 1
            elif body[i] == "{":
                if depth == 0:
                    break
                depth -= 1
        try:
            obj, _ = DECODER.raw_decode(body[i:])
        except ValueError:
            continue
        if isinstance(obj, dict) and obj.get("slug") == slug and "intelligenceIndex" in obj:
            if best is None or len(obj) > len(best):
                best = obj
    if best is None:
        return None
    benchmarks = {s: best[f] for f, s in PAGE_FIELDS.items() if number(best.get(f)) is not None}
    elo = ((best.get("briefcaseBreakdown") or {}).get("overall") or {}).get("elo")
    if number(elo) is not None:
        benchmarks["aa-briefcase"] = elo
    record = {k: best.get(k) for k in IDENTITY}
    creator = best.get("creator") if isinstance(best.get("creator"), dict) else {}
    record.update({"modelCreatorName": best.get("modelCreatorName") or creator.get("name"),
                   "benchmarks": benchmarks, "readFrom": "model-page"})
    return record


def mapped_slugs() -> set[str]:
    """Every configuration the next build maps: the persisted map plus MAP_ADDITIONS, and older measured rows."""
    slugs = {e["slug"] for e in configuration_map(prior_snapshot()[1])}
    for name in SCORE_FILES:
        archive = json.loads((ROOT / "data/research" / name).read_text(encoding="utf-8"))
        for row in archive.get("scores", []):
            sec = row.get("secondary") or {}
            if row.get("boardId") == "aa_intelligence_index" and sec.get("slug") and not sec.get("proxy"):
                slugs.add(sec["slug"])
    return slugs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", required=True)
    parser.add_argument("--slugs", nargs="*", default=[])
    args = parser.parse_args()

    html, body = read(LEADERBOARD)
    key = body.find('"initialModels"')
    if key < 0:
        raise SystemExit("leaderboard has no initialModels payload")
    models, _ = DECODER.raw_decode(body[body.index("[", key):])
    records = {m["slug"]: leaderboard_record(m) for m in models if m.get("slug")}
    wanted = sorted(mapped_slugs() | {e["anchor"] for e in SAME_WEIGHTS} | set(args.slugs))
    missing, failed = [], []
    for n, slug in enumerate(wanted, 1):
        page = None
        for attempt in range(3):
            try:
                _, page = read(MODEL_PAGE.format(slug))
                break
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    # AA has no page for this slug: a real absence, recorded below. The builder still
                    # refuses the payload if the prior v5 snapshot had data for it.
                    page = ""
                    break
                print(f"{slug}: attempt {attempt + 1}: {exc}", file=sys.stderr)
                time.sleep(5.0)
            except OSError as exc:
                print(f"{slug}: attempt {attempt + 1}: {exc}", file=sys.stderr)
                time.sleep(5.0)
        if page is None:
            failed.append(slug)
            continue
        record = page_record(page, slug) if page else None
        if record is None:
            missing.append(slug)
        elif slug not in records or len(record["benchmarks"]) > len(records[slug]["benchmarks"]):
            # Model pages carry the full evaluation set; prefer them when richer.
            records[slug] = record
        print(f"[{n}/{len(wanted)}] {slug}", file=sys.stderr)
        time.sleep(1.0)

    if failed:
        # A page that could not be read is not evidence that AA dropped the configuration.
        raise SystemExit(f"could not read {len(failed)} model page(s): {', '.join(failed)}")
    out = {
        "readAt": time.strftime("%Y-%m-%d"),
        "indexVersion": version_of(html),
        "leaderboardConfigurations": len(models),
        "modelPagesRead": len(wanted),
        "modelPagesWithoutRecord": missing,
        "records": sorted(records.values(), key=lambda r: r["slug"]),
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {args.out}: {len(records)} records, index v{out['indexVersion']}, "
          f"{len(missing)} page(s) without a record", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
