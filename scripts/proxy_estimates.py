"""Proxy estimates for plan rows AA has not scored.

WHY THIS FILE EXISTS
--------------------
AA's public payload carries no Intelligence Index for a handful of models the plans
serve (GLM-5.3-FlashX, Qwen3.8-Flash, Qwen3.8-Omni-Flash, Hy4-preview, plus several serving
variants). MiMo-V2.6-Flash was a proxy until AA published a measured configuration on 2026-10-20. Without a number those rows cannot appear on the
intelligence charts at all.

A single-benchmark bridge was measured and REJECTED: fitting intelligenceIndex ~ GPQA
across the payload's modern records gives R2 0.44 and a p90 residual near 10 AA points,
and it extrapolates nonsense below the fit's range. That is wider than the gaps that
decide the frontier, so a global regression would rank models wrongly.

On the Intelligence Index v5 board, configurations AA ran some of the nine v5 evaluations
on are estimated by component reconstruction (aa_v5_reconstruct.py), not by this file.

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

# B (v5). vendor-anchored estimates on the Intelligence Index v5 scale ----------------------
# The VENDOR_ANCHORED values above are on the v4.3.2 scale and are kept as the record of that
# board. build_aa_v5_snapshot.py reads only this list, and lists every VENDOR_ANCHORED model
# missing from it as not estimated.
#
# Reviewed 2026-11-09, none carried to v5:
#   qwen3.8-flash, qwen3.8-omni-flash: AA v5 gives qwen3-8-27b 20.11 and qwen3-8-max 33.65, a
#     slope near 5.8 index points per GPQA point. Qwen's own table (qwen.ai blog, Qwen3.8 Omni
#     Flash) puts Flash 2.5 GPQA points above 27B, which would place Flash near 34.7, above
#     Max. The calibration is too unstable to publish.
#   hy4-preview: the old anchors (hy3, hy3-preview) have no AA v5 score. Tencent describes Hy4
#     as superseding the preview with further training, so Hy4's score cannot be inherited.
VENDOR_ANCHORED_V5 = []

# C. deliberately NOT estimated -----------------------------------------------------------
UNSCORED = [
    dict(model="omen-alpha",
         reason="No vendor table, no AA configuration and no family anchor; nothing to calibrate "
                "against. Listed as unscored rather than guessed."),
    dict(model="composer-2.5",
         reason="Cursor does not publish an AA Intelligence Index for it; the fork already scores "
                "it on the AA Coding Agent board (38.3008), which is a different metric."),
]
