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
  const res = await axios.get<TrendRow[]>(`${BASE}/forecast_trend_${metric}.json`);
  return res.data;
}

export async function loadRiskSummary(metric: BayesianMetric): Promise<RiskRow[]> {
  const res = await axios.get<RiskRow[]>(`${BASE}/risk_summary_${metric}.json`);
  return res.data;
}

export function forecastImageUrl(metric: BayesianMetric): string {
  return `${BASE}/forecast_${metric}.png`;
}
