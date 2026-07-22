// ─── bayesianData.ts ─────────────────────────────────────────────────────────
// Loads the Bayesian canopy forecast pipeline's outputs:
//   forecast_trend_<metric>.json  -- per-year percentile bands (trend chart)
//   risk_summary_<metric>.json    -- 2027/2028 decline-risk snapshot (risk chart)
//   forecast_<metric>.png         -- static matplotlib KDE plot (direct embed)
//
// Written by bayesian_canopy_forecast_pipeline.py --upload-to-dashboard,
// which uploads to s3://<dashboard-bucket>/data/bayesian/ by default.

import axios from "axios";
import DATA_BASE_URL from "./config";

export type BayesianMetric = "height" | "cover";

export interface TrendRow {
  metric: BayesianMetric;
  scenario: string;
  jurisdiction: string;
  year: number;
  p2_5: number;
  p25: number;
  median: number;
  p75: number;
  p97_5: number;
  mean: number;
}

export interface RiskRow {
  Jurisdiction: string;
  Scenario: string;
  Baseline: number;
  "2027 Decline Risk (%)": number;
  "2028 Decline Risk (%)": number;
  "Net Shift by 2028": number;
}

// Files are uploaded FLAT (no "bayesian/" subfolder) to match this project's
// established three-location upload convention (see
// bayesian_canopy_forecast_pipeline.py's --upload-to-dashboard default),
// same as merged_smap_gedi.json, canopy_cover_bar.json, etc.
const BASE = DATA_BASE_URL;

export async function loadForecastTrend(metric: BayesianMetric): Promise<TrendRow[]> {
  const url = `${BASE}/forecast_trend_${metric}.json`;
  const res = await axios.get(url);
  if (!Array.isArray(res.data)) {
    // The TypeScript generic on axios.get<TrendRow[]>() is compile-time only --
    // it does not validate the actual response at runtime. If the server (or,
    // in local dev, Vite's SPA fallback) returns something else -- an HTML
    // error page, an S3 XML error document, a wrapped object -- axios will
    // still resolve successfully with that as res.data. Without this check,
    // that bad data silently reaches state and crashes later inside .map(),
    // far from the actual cause. Failing here instead gives a clear,
    // actionable error message immediately.
    throw new Error(
      `Expected an array from ${url}, got ${typeof res.data}. ` +
      `Check that the file actually exists at this path (common cause: ` +
      `the pipeline hasn't been run with --upload-to-dashboard yet, or ` +
      `the local dev file is missing from public/data/).`
    );
  }
  return res.data as TrendRow[];
}

export async function loadRiskSummary(metric: BayesianMetric): Promise<RiskRow[]> {
  const url = `${BASE}/risk_summary_${metric}.json`;
  const res = await axios.get(url);
  if (!Array.isArray(res.data)) {
    throw new Error(
      `Expected an array from ${url}, got ${typeof res.data}. ` +
      `Check that the file actually exists at this path.`
    );
  }
  return res.data as RiskRow[];
}

export function forecastImageUrl(metric: BayesianMetric): string {
  return `${BASE}/forecast_${metric}.png`;
}