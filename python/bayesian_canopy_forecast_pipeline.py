#!/usr/bin/env python3
"""
bayesian_canopy_forecast_pipeline.py
======================================================================
Consolidated Bayesian canopy forecasting pipeline for the Central
Virginia Tree Canopy Study — replaces the four standalone scripts
(1_bayesian_stats_business.py, 2_bayesian_pred_scenario_loop.py,
3_bayesian_visualizations_pipeline.py, 4_bayesian_evaluation.py) with
one script structured so each stage is an explicit function with real
inputs/outputs, not a reliance on shared notebook/kernel state.

Fixes applied relative to the original four scripts / notebooks
(see the accompanying chat review for full detail on each):

  1. No shared global state between stages. Each function takes and
     returns explicit values. The fitted PyMC trace is persisted to disk
     via ArviZ's NetCDF format (`az.to_netcdf` / `az.from_netcdf`), so
     the model-fitting stage and the forecasting stage can genuinely run
     as separate processes/jobs later, the same way the LiDAR and GEDI
     pipelines were split into independent SageMaker Processing Jobs
     earlier in this project -- rather than requiring one continuous
     kernel session that breaks on restart.
  2. Data is always loaded from the real source (S3 JSON, or a
     synthetic test fixture for local testing) -- never hand-copied
     into a hardcoded list, which is what caused the original
     1_bayesian_stats_business.py to silently drop Buckingham,
     Rockingham, and Nelson's 2023 row.
  3. `import numpy as np` is present at module level (missing from the
     original 3_bayesian_visualizations_pipeline.py).
  4. Lag computation is calendar-aware: a jurisdiction's "lag1" value is
     only populated if the previous CALENDAR YEAR actually exists in the
     data, not just the previous ROW. Positionally shifting (the
     original approach) silently mislabels a 2-year gap as "lag1" for
     any jurisdiction with a missing year (e.g. Charlottesville, which
     has no 2020 or 2023 GEDI observations).
  5. Forecast-horizon asymmetry across jurisdictions with different last
     available years is now logged explicitly, not silently absorbed.
  6. Supports EITHER canopy height (GEDI02_A, merged_smap_gedi.json) OR
     canopy cover (GEDI02_B, merged_smap_gedi02B.json) via --metric, so
     the pipeline isn't permanently height-only.

Usage — real S3 data, canopy height:
    python bayesian_canopy_forecast_pipeline.py --metric height

Usage — real S3 data, canopy cover:
    python bayesian_canopy_forecast_pipeline.py --metric cover

Usage — synthetic test data (no S3/AWS credentials required):
    python bayesian_canopy_forecast_pipeline.py --metric height --test-data

Usage — skip re-fitting, forecast from a previously saved trace:
    python bayesian_canopy_forecast_pipeline.py --metric height --trace-path out/trace_height.nc --skip-fit
"""

import argparse
import logging
import os
from pathlib import Path

import arviz as az
import numpy as np
import pandas as pd
import pymc as pm

# NOTE: persisting the fitted trace via trace.to_netcdf() requires a netCDF
# write backend -- neither is a PyMC/ArviZ hard dependency, so install one
# explicitly: `pip install h5netcdf` (lighter) or `pip install netCDF4`.
# Discovered as a real gap during testing, not assumed -- ArviZ/PyMC install
# cleanly without either, but trace.to_netcdf() fails at call time without one.

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 0 — Configuration
# ══════════════════════════════════════════════════════════════════════════════

S3_BUCKET = "central-virginia-tree-canopy-project"
SMAP_S3_PREFIX = "dashboard-data/"

METRIC_CONFIG = {
    "height": {
        "s3_filename": "merged_smap_gedi.json",
        "value_col": "canopy_height_mean_m",
        "lag_col": "value_lag1",
        "prior_mu_alpha": 15.0,   # rough prior center, meters
        "label": "Canopy Height (m)",
    },
    "cover": {
        "s3_filename": "merged_smap_gedi02B.json",
        "value_col": "mean_canopy_cover",
        "lag_col": "value_lag1",
        "prior_mu_alpha": 0.4,    # rough prior center, 0-1 fraction
        "label": "Canopy Cover (fraction)",
    },
}

FUTURE_YEARS = [2024, 2025, 2026, 2027, 2028]

SCENARIOS = {
    "Severe Drought": {
        "sm_mean": [0.26, 0.24, 0.23, 0.22, 0.21],
        "sm_std":  [0.038, 0.040, 0.042, 0.045, 0.045],
    },
    "Climate Recovery": {
        "sm_mean": [0.29, 0.32, 0.34, 0.35, 0.36],
        "sm_std":  [0.033, 0.031, 0.029, 0.028, 0.028],
    },
}


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — Data loading (real S3 or synthetic test fixture)
# ══════════════════════════════════════════════════════════════════════════════

def generate_synthetic_test_panel(metric: str, seed: int = 7) -> pd.DataFrame:
    """
    Generate a small, realistic-shaped synthetic panel for local testing
    without needing S3/AWS credentials. Mirrors the real data's structure:
    9 jurisdictions, 2019-2023, with Charlottesville missing 2020 and 2023
    (matching its real GEDI observation gaps) so the calendar-aware lag
    fix can actually be exercised against a genuine gap case.
    """
    rng = np.random.default_rng(seed)
    jurisdictions = [
        "Albemarle", "Augusta", "Buckingham", "Charlottesville", "Fluvanna",
        "Greene", "Louisa", "Nelson", "Rockingham",
    ]
    years = [2019, 2020, 2021, 2022, 2023]
    config = METRIC_CONFIG[metric]

    rows = []
    for j in jurisdictions:
        base = rng.uniform(10, 22) if metric == "height" else rng.uniform(0.25, 0.6)
        for year in years:
            if j == "Charlottesville" and year in (2020, 2023):
                continue  # matches the real data's known gap years
            sm_mean = rng.uniform(0.27, 0.38)
            sm_std = rng.uniform(0.027, 0.036)
            trend = -0.6 * (year - 2019) if metric == "height" else -0.02 * (year - 2019)
            noise = rng.normal(0, 1.0 if metric == "height" else 0.03)
            value = max(0.0, base + trend + noise)
            rows.append({
                "year": year,
                "jurisdiction": j,
                config["value_col"]: round(value, 6),
                "sm_mean_m3m3": round(sm_mean, 6),
                "sm_std": round(sm_std, 6),
            })
    df = pd.DataFrame(rows)
    log.info(f"[TEST DATA] Generated synthetic {metric} panel: "
             f"{len(df)} rows, {df['jurisdiction'].nunique()} jurisdictions, "
             f"years {sorted(df['year'].unique())}")
    return df


def load_panel_data(metric: str, use_test_data: bool = False,
                     bucket: str = S3_BUCKET) -> pd.DataFrame:
    """
    Load the canopy panel data for the given metric ("height" or "cover").
    Always loads the REAL full dataset (from S3, or a synthetic stand-in
    with the same shape for local testing) -- never a hand-copied subset,
    which is what silently dropped Buckingham/Rockingham/Nelson-2023 in
    the original 1_bayesian_stats_business.py.
    """
    if metric not in METRIC_CONFIG:
        raise ValueError(f"Unknown metric '{metric}'. Must be one of {list(METRIC_CONFIG)}.")

    if use_test_data:
        return generate_synthetic_test_panel(metric)

    config = METRIC_CONFIG[metric]
    s3_uri = f"s3://{bucket}/{SMAP_S3_PREFIX}{config['s3_filename']}"
    log.info(f"Loading {metric} panel from {s3_uri}")
    df = pd.read_json(s3_uri)

    juris = sorted(df["jurisdiction"].unique())
    log.info(f"Loaded {len(df)} rows, {len(juris)} jurisdiction(s): {juris}")
    return df


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — Calendar-aware lag engineering
# ══════════════════════════════════════════════════════════════════════════════

def compute_calendar_aware_lag(df: pd.DataFrame, value_col: str,
                                lag_years: int = 1) -> pd.DataFrame:
    """
    Add a `value_lag1` column containing each row's value from exactly
    `lag_years` calendar years earlier, for the SAME jurisdiction --
    populated as NaN if that specific prior year doesn't exist in the
    data, rather than the positional df.groupby(...).shift(1) approach
    used in the original scripts (which silently returns whatever the
    PREVIOUS ROW happens to be, even if that row is 2+ years earlier due
    to a missing year -- e.g. Charlottesville's missing 2020/2023).
    """
    df = df.copy()
    lookup = df.set_index(["jurisdiction", "year"])[value_col]

    def get_lag(row):
        key = (row["jurisdiction"], row["year"] - lag_years)
        return lookup.get(key, np.nan)

    df["value_lag1"] = df.apply(get_lag, axis=1)
    n_before = len(df)
    df_clean = df.dropna(subset=["value_lag1"]).copy()
    log.info(f"Calendar-aware lag: {len(df_clean)}/{n_before} rows have a valid "
             f"{lag_years}-year lag (rows dropped are either each jurisdiction's "
             f"first year, or immediately follow a data gap year)")
    return df_clean


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — Hierarchical Bayesian AR(1) model
# ══════════════════════════════════════════════════════════════════════════════

def fit_hierarchical_ar_model(df_clean: pd.DataFrame, metric: str,
                               draws: int = 1000, tune: int = 1000,
                               target_accept: float = 0.95, seed: int = 42,
                               chains: int = 2, cores: int = 1):
    """
    Fit the hierarchical autoregressive model:
        value_it = alpha_i + beta_sm_mean * sm_mean_it + beta_sm_std * sm_std_it
                   + gamma_autoreg * value_lag1_it + eps_it

    Returns (trace, jurisdiction_names) -- both needed for forecasting,
    and both persisted to disk by the caller so a later, separate process
    can forecast without needing to re-fit or share in-memory state.

    chains/cores default to explicit small values rather than PyMC's
    auto-detection, since auto-detection can fail outright in constrained
    or single-CPU containers (observed directly: ZeroDivisionError inside
    PyMC's BLAS-core-count logic on a 1-vCPU sandbox). Override for a
    production SageMaker instance with more cores available.
    """
    config = METRIC_CONFIG[metric]
    value_col = config["value_col"]

    jurisdiction_cats = df_clean["jurisdiction"].astype("category")
    jurisdiction_idx = jurisdiction_cats.cat.codes.values
    jurisdiction_names = list(jurisdiction_cats.cat.categories)

    y_obs = df_clean[value_col].values
    lagged_y = df_clean["value_lag1"].values
    sm_mean = df_clean["sm_mean_m3m3"].values
    sm_std = df_clean["sm_std"].values

    coords = {"jurisdictions": jurisdiction_names}
    with pm.Model(coords=coords) as model:
        mu_alpha = pm.Normal("mu_alpha", mu=config["prior_mu_alpha"], sigma=5.0)
        sigma_alpha = pm.HalfNormal("sigma_alpha", sigma=3.0)
        alpha = pm.Normal("alpha", mu=mu_alpha, sigma=sigma_alpha, dims="jurisdictions")

        beta_sm_mean = pm.Normal("beta_sm_mean", mu=0.0, sigma=2.0)
        beta_sm_std = pm.Normal("beta_sm_std", mu=0.0, sigma=2.0)
        gamma_autoreg = pm.Normal("gamma_autoreg", mu=0.0, sigma=1.0)

        sigma_residual = pm.Exponential("sigma_residual", lam=1.0)

        mu_t = (
            alpha[jurisdiction_idx]
            + beta_sm_mean * sm_mean
            + beta_sm_std * sm_std
            + gamma_autoreg * lagged_y
        )
        pm.Normal("y_likelihood", mu=mu_t, sigma=sigma_residual, observed=y_obs)

        trace = pm.sample(draws=draws, tune=tune, target_accept=target_accept,
                           random_seed=seed, chains=chains, cores=cores,
                           progressbar=False)

    log.info(f"Model fit complete. Jurisdictions: {jurisdiction_names}")
    return trace, jurisdiction_names


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — Scenario simulation
# ══════════════════════════════════════════════════════════════════════════════

def get_baseline_values(df: pd.DataFrame, value_col: str, jurisdictions: list) -> dict:
    """
    Get each jurisdiction's most recent available value as the forecast
    baseline. Logs explicitly (rather than silently) when a jurisdiction's
    last available year differs from the panel's overall most recent
    year -- e.g. Charlottesville lacking 2023 data means its forecast is
    effectively one year further ahead of its last real observation than
    jurisdictions with a full 2023 row.
    """
    panel_max_year = df["year"].max()
    baselines = {}
    for j in jurisdictions:
        j_data = df[df["jurisdiction"] == j]
        last_year = j_data["year"].max()
        baselines[j] = j_data.loc[j_data["year"] == last_year, value_col].values[0]
        if last_year != panel_max_year:
            log.warning(f"[{j}] last available year is {last_year}, not the panel "
                        f"max ({panel_max_year}) -- its forecast horizon starts "
                        f"{panel_max_year - last_year} year(s) further from its "
                        f"last real observation than other jurisdictions.")
    return baselines


def run_scenario_simulation(trace, jurisdictions: list, baselines: dict,
                             scenarios: dict = SCENARIOS,
                             future_years: list = FUTURE_YEARS) -> dict:
    """
    Vectorized posterior forward simulation across all MCMC draws, for
    each jurisdiction x scenario x future year. Returns:
        {scenario_name: {jurisdiction: array of shape (n_years, n_draws)}}
    """
    posterior = trace.posterior
    n_chains = posterior.sizes["chain"]
    n_draws_per_chain = posterior.sizes["draw"]
    n_chains_draws = n_chains * n_draws_per_chain

    posterior_alpha = posterior["alpha"].values.reshape(n_chains_draws, len(jurisdictions))
    posterior_beta_mean = posterior["beta_sm_mean"].values.flatten()
    posterior_beta_std = posterior["beta_sm_std"].values.flatten()
    posterior_gamma = posterior["gamma_autoreg"].values.flatten()
    posterior_sigma = posterior["sigma_residual"].values.flatten()

    simulation_results = {}
    for scen_name, vectors in scenarios.items():
        log.info(f"Running forecast loop for scenario: {scen_name}...")
        jurisdiction_forecasts = {}

        for j_idx, j_name in enumerate(jurisdictions):
            canopy_sim = np.zeros((len(future_years), n_chains_draws))
            last_value = np.full(n_chains_draws, baselines[j_name])

            for t_idx, year in enumerate(future_years):
                curr_sm_mean = vectors["sm_mean"][t_idx]
                curr_sm_std = vectors["sm_std"][t_idx]

                mu_pred = (
                    posterior_alpha[:, j_idx]
                    + posterior_beta_mean * curr_sm_mean
                    + posterior_beta_std * curr_sm_std
                    + posterior_gamma * last_value
                )
                simulated = np.random.normal(mu_pred, posterior_sigma)
                canopy_sim[t_idx, :] = simulated
                last_value = simulated

            jurisdiction_forecasts[j_name] = canopy_sim

        simulation_results[scen_name] = jurisdiction_forecasts

    return simulation_results


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — Visualization
# ══════════════════════════════════════════════════════════════════════════════

def plot_bayesian_forecasts(simulation_results: dict, jurisdictions: list,
                             metric_label: str, output_path: str,
                             future_years: list = FUTURE_YEARS):
    """
    Side-by-side probability density plots comparing 2027 and 2028
    forecasts across all scenarios, for each jurisdiction. Saves to
    output_path instead of plt.show(), since this needs to run headless
    in a SageMaker Processing Job.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import seaborn as sns

    idx_2027 = future_years.index(2027)
    idx_2028 = future_years.index(2028)
    colors = {"Severe Drought": "#e66101", "Climate Recovery": "#5e3c99"}

    n_jurisdictions = len(jurisdictions)
    fig, axes = plt.subplots(nrows=n_jurisdictions, ncols=2,
                              figsize=(14, 3.5 * n_jurisdictions), sharey="row")
    if n_jurisdictions == 1:
        axes = np.expand_dims(axes, axis=0)

    for j_idx, j_name in enumerate(jurisdictions):
        ax_2027 = axes[j_idx, 0]
        ax_2028 = axes[j_idx, 1]

        for scen_name, color in colors.items():
            draws_2027 = simulation_results[scen_name][j_name][idx_2027, :]
            draws_2028 = simulation_results[scen_name][j_name][idx_2028, :]

            sns.kdeplot(draws_2027, ax=ax_2027, color=color, fill=True, alpha=0.25,
                        linewidth=2, label=scen_name)
            ax_2027.axvline(np.mean(draws_2027), color=color, linestyle="--", alpha=0.8)

            sns.kdeplot(draws_2028, ax=ax_2028, color=color, fill=True, alpha=0.25,
                        linewidth=2, label=scen_name)
            ax_2028.axvline(np.mean(draws_2028), color=color, linestyle="--", alpha=0.8)

        ax_2027.set_title(f"{j_name} {metric_label} - 2027 Projection", fontsize=11, weight="bold")
        ax_2028.set_title(f"{j_name} {metric_label} - 2028 Projection", fontsize=11, weight="bold")
        ax_2027.set_ylabel("Probability Density", fontsize=10)
        ax_2028.set_ylabel("")
        ax_2027.set_xlabel(metric_label, fontsize=10)
        ax_2028.set_xlabel(metric_label, fontsize=10)
        ax_2027.grid(True, linestyle=":", alpha=0.6)
        ax_2028.grid(True, linestyle=":", alpha=0.6)

        if j_idx == 0:
            ax_2027.legend(title="Scenarios", loc="upper left", frameon=True)

    plt.tight_layout()
    plt.savefig(output_path, dpi=120)
    plt.close(fig)
    log.info(f"Saved forecast visualization to {output_path}")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6 — Risk evaluation
# ══════════════════════════════════════════════════════════════════════════════

def evaluate_decline_probabilities(simulation_results: dict, jurisdictions: list,
                                    baselines: dict,
                                    future_years: list = FUTURE_YEARS) -> pd.DataFrame:
    """
    Calculates the Bayesian probability that the forecast value in 2027
    and 2028 falls below each jurisdiction's baseline value.
    """
    idx_2027 = future_years.index(2027)
    idx_2028 = future_years.index(2028)

    rows = []
    for j_name in jurisdictions:
        baseline = baselines[j_name]
        for scen_name, juris_data in simulation_results.items():
            draws_2027 = juris_data[j_name][idx_2027, :]
            draws_2028 = juris_data[j_name][idx_2028, :]

            prob_decline_2027 = np.mean(draws_2027 < baseline) * 100
            prob_decline_2028 = np.mean(draws_2028 < baseline) * 100
            drift_2028 = np.mean(draws_2028) - baseline

            rows.append({
                "Jurisdiction": j_name,
                "Scenario": scen_name,
                "Baseline": round(float(baseline), 4),
                "2027 Decline Risk (%)": round(prob_decline_2027, 1),
                "2028 Decline Risk (%)": round(prob_decline_2028, 1),
                "Net Shift by 2028": round(drift_2028, 4),
            })

    return pd.DataFrame(rows)

def export_forecast_trend_json(simulation_results: dict, jurisdictions: list,
                                metric: str, future_years: list = FUTURE_YEARS
                                ) -> pd.DataFrame:
    """
    Build a long-format table of forecast percentiles per
    (scenario, jurisdiction, year), for an interactive median + uncertainty
    band trend chart in the dashboard. Distinct from evaluate_decline_probabilities,
    which only reports single-year (2027/2028) decline-risk snapshots -- this
    covers every year across the full forecast horizon.
    """
    rows = []
    for scen_name, juris_data in simulation_results.items():
        for j_name in jurisdictions:
            draws_by_year = juris_data[j_name]  # shape (n_years, n_draws)
            for t_idx, year in enumerate(future_years):
                draws = draws_by_year[t_idx, :]
                rows.append({
                    "metric": metric,
                    "scenario": scen_name,
                    "jurisdiction": j_name,
                    "year": year,
                    "p2_5": round(float(np.percentile(draws, 2.5)), 4),
                    "p25": round(float(np.percentile(draws, 25)), 4),
                    "median": round(float(np.percentile(draws, 50)), 4),
                    "p75": round(float(np.percentile(draws, 75)), 4),
                    "p97_5": round(float(np.percentile(draws, 97.5)), 4),
                    "mean": round(float(np.mean(draws)), 4),
                })
    return pd.DataFrame(rows)


def upload_dashboard_artifacts(targets: list, local_paths: list) -> None:
    """
    Upload generated artifacts (PNG + JSON) to one or more S3 destinations,
    so the React dashboard can fetch them the same way it already fetches
    merged_smap_gedi.json, canopy_cover_bar.json, etc.

    targets: list of (bucket, prefix) tuples. The same set of local files
    is uploaded to every destination in the list -- useful since this
    project has, at various points, mirrored dashboard data across more
    than one bucket/prefix combination (e.g. both
    s3://central-va-tree-canopy-dashboard/data/bayesian/ and
    s3://central-va-tree-canopy-dashboard/dashboard-data/).
    """
    import boto3
    s3 = boto3.client("s3")
    content_types = {
        ".png": "image/png",
        ".json": "application/json",
        ".csv": "text/csv",
    }
    for bucket, s3_prefix in targets:
        for local_path in local_paths:
            local_path = Path(local_path)
            ext = local_path.suffix
            key = f"{s3_prefix}{local_path.name}"
            s3.upload_file(
                str(local_path), bucket, key,
                ExtraArgs={"ContentType": content_types.get(ext, "application/octet-stream")},
            )
            log.info(f"Uploaded {local_path.name} -> s3://{bucket}/{key}")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 7 — Main pipeline
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Bayesian canopy forecasting pipeline")
    parser.add_argument("--metric", choices=["height", "cover"], default="height",
                         help="Which GEDI-derived metric to model: height (GEDI02_A) or cover (GEDI02_B)")
    parser.add_argument("--test-data", action="store_true",
                         help="Use synthetic test data instead of loading from S3")
    parser.add_argument("--bucket", default=S3_BUCKET)
    parser.add_argument("--output-dir", default="/opt/ml/processing/output")
    parser.add_argument("--draws", type=int, default=1000)
    parser.add_argument("--tune", type=int, default=1000)
    parser.add_argument("--chains", type=int, default=2)
    parser.add_argument("--cores", type=int, default=1)
    parser.add_argument("--trace-path", default=None,
                         help="Path to a previously saved trace (.nc). If provided with "
                              "--skip-fit, forecasting runs from this trace instead of refitting.")
    parser.add_argument("--skip-fit", action="store_true",
                         help="Skip model fitting and load --trace-path instead")
    parser.add_argument("--upload-to-dashboard", action="store_true",
                         help="Upload the PNG + JSON outputs to one or more dashboard S3 locations")
    parser.add_argument("--dashboard-target", action="append", default=None,
                         metavar="BUCKET/PREFIX",
                         help="S3 destination as 'bucket/prefix' (e.g. "
                              "'central-va-tree-canopy-dashboard/dashboard-data/'). "
                              "Repeatable -- pass multiple times to upload to multiple "
                              "locations. If --upload-to-dashboard is set and this is "
                              "never passed, defaults to this project's established "
                              "three-location convention (matching upload_to_s3_all in "
                              "multivariate_data_pipeline.ipynb): "
                              "'central-virginia-tree-canopy-project/dashboard-data/', "
                              "'central-va-tree-canopy-dashboard/dashboard-data/', and "
                              "'central-va-tree-canopy-dashboard/data/'.")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    config = METRIC_CONFIG[args.metric]

    # Stage 1: Load data
    df = load_panel_data(args.metric, use_test_data=args.test_data, bucket=args.bucket)

    # Stage 2: Calendar-aware lag engineering
    df_clean = compute_calendar_aware_lag(df, config["value_col"])

    # Stage 3: Fit (or load) the hierarchical model
    trace_path = args.trace_path or os.path.join(args.output_dir, f"trace_{args.metric}.nc")
    if args.skip_fit:
        log.info(f"Loading previously fit trace from {trace_path}")
        trace = az.from_netcdf(trace_path)
        jurisdictions = sorted(df["jurisdiction"].unique())
    else:
        trace, jurisdictions = fit_hierarchical_ar_model(
            df_clean, args.metric, draws=args.draws, tune=args.tune,
            chains=args.chains, cores=args.cores,
        )
        trace.to_netcdf(trace_path)
        log.info(f"Saved fitted trace to {trace_path}")
        print(az.summary(trace, var_names=["mu_alpha", "beta_sm_mean", "beta_sm_std", "gamma_autoreg"]))

    # Stage 4: Scenario simulation
    baselines = get_baseline_values(df, config["value_col"], jurisdictions)
    simulation_results = run_scenario_simulation(trace, jurisdictions, baselines)

    # Stage 5: Visualization (static PNG, for direct embedding)
    plot_path = os.path.join(args.output_dir, f"forecast_{args.metric}.png")
    plot_bayesian_forecasts(simulation_results, jurisdictions, config["label"], plot_path)

    # Stage 6: Risk evaluation (single-year 2027/2028 decline-risk snapshot)
    risk_df = evaluate_decline_probabilities(simulation_results, jurisdictions, baselines)
    risk_csv_path = os.path.join(args.output_dir, f"risk_summary_{args.metric}.csv")
    risk_json_path = os.path.join(args.output_dir, f"risk_summary_{args.metric}.json")
    risk_df.to_csv(risk_csv_path, index=False)
    risk_df.to_json(risk_json_path, orient="records")

    # Stage 7: Trend export (full-horizon percentile bands, for the
    # interactive dashboard's median + uncertainty-band chart)
    trend_df = export_forecast_trend_json(simulation_results, jurisdictions, args.metric)
    trend_json_path = os.path.join(args.output_dir, f"forecast_trend_{args.metric}.json")
    trend_df.to_json(trend_json_path, orient="records")

    print("\n" + "=" * 70)
    print(f"BAYESIAN {config['label'].upper()} RISK ASSESSMENT REPORT")
    print("=" * 70)
    print(risk_df.to_string(index=False))
    print("=" * 70)
    log.info(f"Saved risk summary to {risk_csv_path} / {risk_json_path}")
    log.info(f"Saved forecast trend data to {trend_json_path}")

    # Stage 8: Optional upload to one or more dashboard S3 locations
    if args.upload_to_dashboard:
        if args.dashboard_target:
            targets = []
            for target_str in args.dashboard_target:
                bucket, _, prefix = target_str.partition("/")
                if not prefix:
                    raise ValueError(
                        f"--dashboard-target '{target_str}' must be in 'bucket/prefix' "
                        f"form, e.g. 'central-va-tree-canopy-dashboard/dashboard-data/'"
                    )
                if not prefix.endswith("/"):
                    prefix += "/"
                targets.append((bucket, prefix))
        else:
            # Default: mirror to all three locations used by this project's
            # established upload_to_s3_all convention (see
            # multivariate_data_pipeline.ipynb), not just the dashboard's
            # own bucket.
            targets = [
                ("central-virginia-tree-canopy-project", "dashboard-data/"),
                ("central-va-tree-canopy-dashboard", "dashboard-data/"),
                ("central-va-tree-canopy-dashboard", "data/"),
            ]

        upload_dashboard_artifacts(targets, [plot_path, risk_json_path, trend_json_path])


if __name__ == "__main__":
    main()
