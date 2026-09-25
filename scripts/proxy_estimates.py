"""Proxy estimates for plan rows AA has not scored.

WHY THIS FILE EXISTS
--------------------
AA's public payload carries no Intelligence Index for a handful of models the plans
serve (MiMo-V2.6-Flash, GLM-5.3-FlashX, Qwen3.8-Flash, Qwen3.8-Omni-Flash, Hy4-preview,
plus several serving variants). Without a number those rows cannot appear on the
intelligence charts at all.

A single-benchmark bridge was measured and REJECTED: fitting intelligenceIndex ~ GPQA
across the payload's modern records gives R2 0.44 and a p90 residual near 10 AA points,
and it extrapolates nonsense below the fit's range. That is wider than the gaps that
decide the frontier, so a global regression would rank models wrongly.

What is used instead, in descending confidence:

  A. SAME-WEIGHTS SERVING VARIANT (band +-1.5)
     The row is the same model served faster/cheaper (verified from the provider's own
     description). The AA score of the base configuration is inherited unchanged.

  B. SAME-VENDOR ANCHOR (band +-5)
     The vendor publishes a benchmark table containing both the missing model and a
     sibling AA HAS scored. The sibling anchors the family; the vendor delta carries the
     new model. Where a family has two AA-scored points, the local slope (AA points per
     benchmark point) is used; it is steep and saturation-prone in this range, which is
     why the band is wide.

Every estimate is written with estimate_method, estimate_basis, estimate_band and
estimate_anchor so a reader can audit or reject it, and charts label these rows
"[proxy]" (zh "[代理]") so they can never be mistaken for an AA measurement or for
AA's own published estimates.
"""

# A. same weights, different serving tier -------------------------------------------------
SAME_WEIGHTS = [
    dict(model="glm-5.3-flashx", anchor="glm-5-3-flash", band=1.5,
         note="Z.ai/OpenRouter describe FlashX as the high-speed variant of GLM-5.3-Flash; "
              "same weights, faster serving.",
         basis=["https://open-ocr.com/engines/openrouter-z-ai-glm-5.3-flashx",
                "https://llmbase.ai/models/z-ai/glm-5.3-flashx/"]),
    dict(model="muse-spark-1.3-contributor", anchor="muse-spark-1-3", band=1.5,
         note="Contributor tier of the same Muse Spark 1.3 model; the provider prices it as "
              "the same capability at a lower rate.",
         basis=["https://commandcode.ai/docs/plans/goat"]),
    dict(model="muse-spark-1.2-contributor", anchor="muse-spark-1-2", band=1.5,
         note="Contributor tier of the same Muse Spark 1.2 model.",
         basis=["https://commandcode.ai/docs/plans/goat"]),
    dict(model="deepseek-v4-flash-fast", anchor="deepseek-v4-flash", band=1.5,
         note="Fast serving variant of DeepSeek V4 Flash; the provider lists it as the same "
              "model with different allowance.",
         basis=["https://commandcode.ai/docs/plans/goat"]),
    dict(model="kimi-k2.7-code-highspeed", anchor="kimi-k2-7-code", band=1.5,
         note="HighSpeed serving variant of Kimi K2.7 Code; the provider lists it as the same "
              "model with an independent allowance.",
         basis=["https://commandcode.ai/docs/plans/goat"]),
    dict(model="glm-5.2-fast", anchor="glm-5-2", band=1.5,
         note="Fast serving variant of GLM-5.2; the provider lists it as the same model with "
              "an independent allowance.",
         basis=["https://commandcode.ai/docs/plans/goat"]),
]

# B. vendor-anchored, family slope --------------------------------------------------------
VENDOR_ANCHORED = [
    dict(model="mimo-v2.6-flash", value=44.30, band=2.5,
         anchor="mimo-v2-6-pro",
         method="Two independent within-family readings, averaged: (1) the vendor's own DeepSWE "
                "v1.1 table puts Flash at 67.9 against Pro's 71.9, and AA scores Pro at 46.3242, "
                "giving 43.75; (2) the MiMo V2.5 pair in the same payload has Pro at 1.032x its "
                "non-Pro sibling, giving 44.88. Midpoint adopted.",
         note="Vendor tables describe Flash as trailing Pro on agentic tasks while staying in the "
              "same tier. AA has not scored the Flash configuration.",
         basis=["https://yfarmx.com/ai/llms/mimo-v2-6/",
                "https://cheapestinference.com/blog/mimo-v2-6/",
                "https://rankllms.com/models/mimo-v2-6-flash/"]),
    dict(model="qwen3.8-flash", value=39.70, band=5.0,
         anchor="qwen3-8-27b + qwen3-8-max",
         method="Within-family calibration on AA's own GPQA for two Qwen 3.8 points "
                "(27B: 33.6962 at GPQA 90.51; Max: 45.4152 at GPQA 92.83) gives a local slope of "
                "5.05 AA points per GPQA point. Vendor GPQA for Qwen3.8-Flash is 91.7.",
         note="Vendor GPQA and AA GPQA agree within ~1 point on this family, which is what makes "
              "the anchor usable; the slope is steep, hence the +-5 band.",
         basis=["https://www.together.ai/models/qwen3-8-flash",
                "https://www.datacamp.com/blog/qwen3-8-max"]),
    dict(model="qwen3.8-omni-flash", value=36.20, band=5.0,
         anchor="qwen3-8-27b + qwen3-8-max",
         method="Same within-family calibration as Qwen3.8-Flash (5.05 AA points per GPQA point), "
                "applied to the vendor's GPQA Diamond of 91.0 for the omni-modal Flash.",
         note="Arrow/paper report GPQA 91.0; AA has no scored configuration for this model.",
         basis=["https://qwenlm.github.io/blog/qwen3.8-omni-flash/",
                "https://arxiv.org/html/2609.25611"]),
    dict(model="hy4-preview", value=27.50, band=3.0,
         anchor="hy3 + hy3-preview",
         method="Within-family calibration on AA's GPQA for Hy3 (25.2973 at GPQA 89.70) and "
                "Hy3-preview (22.7362 at GPQA 86.67) gives a local slope of 0.85 AA points per "
                "GPQA point. Tencent's table puts Hy4-preview at GPQA 92.3 against Hy3's 90.4.",
         note="Shallow slope: this family barely moves on GPQA, so the estimate stays close to Hy3.",
         basis=["https://emergent.sh/learn/hy3-preview-vs-hy4-preview",
                "https://aitoolsreview.co.uk/insights/tencent-hy4-preview"]),
]

# C. deliberately NOT estimated -----------------------------------------------------------
UNSCORED = [
    dict(model="omen-alpha",
         reason="No vendor table, no AA configuration and no family anchor; nothing to calibrate "
                "against. Listed as unscored rather than guessed."),
    dict(model="composer-2.5",
         reason="Cursor does not publish an AA Intelligence Index for it; the fork already scores "
                "it on the AA Coding Agent board (38.3008), which is a different metric."),
]
