## Cell 13 — Generate Review-Ready Regression Diagnostics & JSON Artifacts
##
## Produces JSON artifacts for internal team review, going beyond raw
## coefficients/p-values to include the same diagnostic scrutiny applied
## manually earlier (leverage, Cook's distance, VIF, leave-one-out
## sensitivity for cross-sectional models; cluster count and clustered-vs-
## robust SE sensitivity for panel FE models). Each finding gets a list of
## plain-language "confidence_flags" and a one-line reviewer recommendation,
## so a non-statistician can approve or deny each result with the actual
## caveats in front of them -- not just a p-value that might be an artifact
## of a single high-leverage jurisdiction (as the Diabetes finding turned
## out to be: p=0.0000, R²=0.967 on n=9, driven almost entirely by
## Charlottesville's hat value of 0.9999 / Cook's D of 367.7).
##
## Requires: Cell 12 (the fixed regression cell) to have already run, so
## df_reg, canopy_vars, control_vars, outcome_vars, CROSS_SECTIONAL_OUTCOMES,
## and results_df all exist.
##
## Outputs:
##   regression_review_artifacts.json   -- full results + diagnostics + flags
##   regression_coefficient_plot.json   -- lightweight forest-plot-ready summary

import json
import numpy as np
import statsmodels.api as sm
from statsmodels.stats.outliers_influence import variance_inflation_factor

REVIEW_JSON_PATH = OUTPUT_DIR / "regression_review_artifacts.json"
COEF_PLOT_JSON_PATH = OUTPUT_DIR / "regression_coefficient_plot.json"

LOW_N_THRESHOLD = 15            # below this, flag small-sample risk
MIN_RESIDUAL_DF = 5             # below this, flag near-saturated model risk
HIGH_HAT_MULTIPLIER = 2.0       # hat > this * mean(hat) => high leverage
COOKS_D_THRESHOLD_FACTOR = 4    # Cook's D > factor/n => influential point
VIF_THRESHOLD = 10
MIN_CLUSTERS_FOR_ROBUST_SE = 20 # panel FE clustered-SE reliability threshold


def _cross_sectional_diagnostics(df_reg, canopy_var, outcome_var, control_vars):
    """
    Recompute the cross-sectional model and return leverage, Cook's distance,
    VIF, and a leave-one-out sensitivity check on the single highest-leverage
    observation -- exactly the checks that revealed the Diabetes finding was
    fragile.
    """
    needed = [outcome_var, canopy_var] + control_vars
    cross = df_reg.reset_index().groupby("jurisdiction")[needed].mean().dropna()
    if len(cross) < 5:
        return None

    y = cross[outcome_var]
    X = sm.add_constant(cross[[canopy_var] + control_vars])
    result = sm.OLS(y, X).fit(cov_type="HC1")

    influence = result.get_influence()
    hat = influence.hat_matrix_diag
    cooks_d = influence.cooks_distance[0]
    n = len(cross)
    k = X.shape[1]

    vif_data = {}
    for i, col in enumerate(X.columns):
        if col == "const":
            continue
        try:
            vif_data[col] = float(variance_inflation_factor(X.values, i))
        except Exception:
            vif_data[col] = None

    max_hat_idx = int(np.argmax(hat))
    max_hat_juris = str(cross.index[max_hat_idx])
    max_cooks_idx = int(np.argmax(cooks_d))
    max_cooks_juris = str(cross.index[max_cooks_idx])

    loo_result = None
    try:
        cross_loo = cross.drop(index=cross.index[max_cooks_idx])
        y_loo = cross_loo[outcome_var]
        X_loo = sm.add_constant(cross_loo[[canopy_var] + control_vars])
        fit_loo = sm.OLS(y_loo, X_loo).fit(cov_type="HC1")
        loo_result = {
            "excluded_jurisdiction": max_cooks_juris,
            "n_obs": int(fit_loo.nobs),
            "beta": round(float(fit_loo.params.get(canopy_var, float("nan"))), 4),
            "p_value": round(float(fit_loo.pvalues.get(canopy_var, float("nan"))), 4),
            "r_squared": round(float(fit_loo.rsquared), 3),
        }
    except Exception as exc:
        log.warning(f"LOO check failed for {outcome_var} ~ {canopy_var}: {exc}")

    return {
        "n_obs": n,
        "n_params": k,
        "residual_df": n - k,
        "max_hat": round(float(hat[max_hat_idx]), 4),
        "max_hat_jurisdiction": max_hat_juris,
        "mean_hat": round(float(np.mean(hat)), 4),
        "max_cooks_d": round(float(cooks_d[max_cooks_idx]), 2),
        "max_cooks_d_jurisdiction": max_cooks_juris,
        "cooks_d_threshold": round(COOKS_D_THRESHOLD_FACTOR / n, 4),
        "vif": {k2: (round(v2, 2) if v2 is not None else None) for k2, v2 in vif_data.items()},
        "leave_one_out": loo_result,
    }


def _panel_diagnostics(df_reg, canopy_var, outcome_var, control_vars):
    """
    For panel FE models: compare clustered vs. robust (non-clustered) SE
    p-values as a sensitivity check against the small-cluster-count problem
    -- exactly the check that flagged the Violent Crime finding's p=0.027
    as sensitive to only having ~9 clusters.
    """
    req = [outcome_var, canopy_var] + control_vars
    df_m = df_reg[req].dropna()
    if len(df_m) < 10:
        return None

    n_clusters = df_m.reset_index()["jurisdiction"].nunique()
    y = df_m[outcome_var]
    X = sm.add_constant(df_m[[canopy_var] + control_vars])
    try:
        model = PanelOLS(y, X, entity_effects=True, time_effects=True)
        fit_clustered = model.fit(cov_type="clustered", cluster_entity=True)
        fit_robust = model.fit(cov_type="robust")
    except Exception as exc:
        log.warning(f"Panel diagnostics failed for {outcome_var} ~ {canopy_var}: {exc}")
        return None

    return {
        "n_obs": int(len(df_m)),
        "n_clusters": int(n_clusters),
        "min_recommended_clusters": MIN_CLUSTERS_FOR_ROBUST_SE,
        "p_value_clustered": round(float(fit_clustered.pvalues.get(canopy_var, float("nan"))), 4),
        "p_value_robust_unclustered": round(float(fit_robust.pvalues.get(canopy_var, float("nan"))), 4),
    }


def _build_confidence_flags(model_type, diagnostics, p_value):
    """Translate raw diagnostics into plain-language flags a non-statistician
    reviewer can act on directly."""
    if diagnostics is None:
        return ["diagnostics_unavailable"]

    flags = []
    if model_type == "cross_sectional_OLS":
        n = diagnostics["n_obs"]
        if n < LOW_N_THRESHOLD:
            flags.append(f"small_sample (n={n})")
        if diagnostics["residual_df"] < MIN_RESIDUAL_DF:
            flags.append(f"near_saturated_model (residual_df={diagnostics['residual_df']})")
        if diagnostics["max_hat"] > HIGH_HAT_MULTIPLIER * diagnostics["mean_hat"]:
            flags.append(f"high_leverage_point ({diagnostics['max_hat_jurisdiction']}, "
                          f"hat={diagnostics['max_hat']})")
        if diagnostics["max_cooks_d"] > diagnostics["cooks_d_threshold"]:
            flags.append(f"influential_point ({diagnostics['max_cooks_d_jurisdiction']}, "
                          f"Cook's D={diagnostics['max_cooks_d']})")
        vif_vals = [v for v in diagnostics["vif"].values() if v is not None]
        if vif_vals and max(vif_vals) > VIF_THRESHOLD:
            flags.append(f"multicollinearity_risk (max VIF={max(vif_vals):.1f})")

        loo = diagnostics.get("leave_one_out")
        if loo is not None and p_value is not None and not (isinstance(p_value, float) and np.isnan(p_value)):
            if p_value < 0.05:
                if loo["p_value"] >= 0.05:
                    flags.append(f"NOT_robust_to_leave_one_out (drops to p={loo['p_value']} "
                                 f"without {loo['excluded_jurisdiction']})")
                else:
                    flags.append(f"robust_to_leave_one_out (excluding {loo['excluded_jurisdiction']})")

    elif model_type.startswith("panel_FE"):
        if diagnostics["n_clusters"] < diagnostics["min_recommended_clusters"]:
            flags.append(f"few_clusters (n={diagnostics['n_clusters']}, "
                          f"recommended >= {diagnostics['min_recommended_clusters']})")
        if (p_value is not None and not (isinstance(p_value, float) and np.isnan(p_value))
                and p_value < 0.05 and diagnostics["p_value_robust_unclustered"] >= 0.05):
            flags.append("NOT_robust_to_unclustered_SE")

    return flags if flags else ["no_major_concerns_detected"]


def _recommend_use(flags, p_value):
    """Short, plain-language verdict for a policy-facing reviewer."""
    blocking = [f for f in flags
                if f.startswith("NOT_robust") or f.startswith("small_sample")
                or f.startswith("near_saturated")]
    if p_value is None or (isinstance(p_value, float) and np.isnan(p_value)):
        return "Not estimable -- insufficient data."
    if blocking:
        return "Do NOT use for policy decisions without further data collection -- statistical result is fragile."
    if p_value < 0.05:
        return "Statistically significant and passes basic robustness checks -- still treat as hypothesis-generating given small N."
    return "Not statistically significant at conventional thresholds."


# ── Build the full review artifact ───────────────────────────────────────────
review_rows = []
for _, res_row in results_df.iterrows():
    outcome_label = res_row["outcome"]
    canopy_var = res_row["canopy_var"]
    model_type = res_row["model_type"]
    p_value = res_row["p_value"]

    outcome_col = next((k for k, v in outcome_vars.items() if v == outcome_label), None)

    if model_type == "cross_sectional_OLS":
        diagnostics = _cross_sectional_diagnostics(df_reg, canopy_var, outcome_col, control_vars)
    else:
        diagnostics = _panel_diagnostics(df_reg, canopy_var, outcome_col, control_vars)

    flags = _build_confidence_flags(model_type, diagnostics, p_value)
    recommendation = _recommend_use(flags, p_value)

    review_rows.append({
        **res_row.to_dict(),
        "diagnostics": diagnostics,
        "confidence_flags": flags,
        "reviewer_recommendation": recommendation,
    })

with open(REVIEW_JSON_PATH, "w") as f:
    json.dump(review_rows, f, indent=2, default=str)
log.info(f"Saved review-ready regression artifacts to {REVIEW_JSON_PATH}")

# ── Lightweight coefficient-plot-ready JSON (forest plot data) ───────────────
coef_plot_rows = []
for row in review_rows:
    concern_flags = [f for f in row["confidence_flags"] if f != "no_major_concerns_detected"]
    coef_plot_rows.append({
        "outcome": row["outcome"],
        "canopy_var": row["canopy_var"],
        "model_type": row["model_type"],
        "beta": row["beta"],
        "p_value": row["p_value"],
        "n_obs": row["n_obs"],
        "significant": row["significant"],
        "flag_count": len(concern_flags),
        "trustworthy": len([f for f in concern_flags
                             if f.startswith("NOT_robust") or f.startswith("small_sample")
                             or f.startswith("near_saturated")]) == 0,
    })

with open(COEF_PLOT_JSON_PATH, "w") as f:
    json.dump(coef_plot_rows, f, indent=2, default=str)
log.info(f"Saved coefficient-plot-ready JSON to {COEF_PLOT_JSON_PATH}")

print("\n" + "=" * 70)
print("REVIEW SUMMARY")
print("=" * 70)
for row in review_rows:
    print(f"\n{row['outcome']} ~ {row['canopy_var']} ({row['model_type']})")
    print(f"  beta={row['beta']}  p={row['p_value']}  n={row['n_obs']}")
    for flag in row["confidence_flags"]:
        print(f"    - {flag}")
    print(f"  => {row['reviewer_recommendation']}")
