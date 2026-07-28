// ─── regressionData.ts ───────────────────────────────────────────────────────
// Loads the multivariate regression pipeline's review artifacts:
//   regression_coefficient_plot.json  -- lightweight, for the coefficient chart
//   regression_review_artifacts.json  -- full diagnostics, for the review table
//
// Written by Cell 37 of multivariate_data_pipeline.ipynb.

import axios from "axios";
import DATA_BASE_URL from "./config";

export interface LeaveOneOut {
  excluded_jurisdiction: string;
  n_obs: number;
  beta: number;
  p_value: number;
  r_squared: number;
}

export interface Diagnostics {
  n_obs: number;
  // cross-sectional-specific
  n_params?: number;
  residual_df?: number;
  max_hat?: number;
  max_hat_jurisdiction?: string;
  mean_hat?: number;
  max_cooks_d?: number;
  max_cooks_d_jurisdiction?: string;
  cooks_d_threshold?: number;
  vif?: Record<string, number>;
  leave_one_out?: LeaveOneOut | null;
  // panel-FE-specific
  n_clusters?: number;
  min_recommended_clusters?: number;
  p_value_clustered?: number;
  p_value_robust_unclustered?: number;
}

export interface ReviewArtifact {
  outcome: string;
  canopy_var: string;
  model_type: string;
  beta: number;
  p_value: number;
  r_squared: number;
  n_obs: number;
  significant: boolean;
  diagnostics: Diagnostics | null;
  confidence_flags: string[];
  reviewer_recommendation: string;
}

export interface CoefficientPlotRow {
  outcome: string;
  canopy_var: string;
  model_type: string;
  beta: number;
  p_value: number;
  n_obs: number;
  significant: boolean;
  flag_count: number;
  trustworthy: boolean;
}

async function fetchValidatedArray<T>(url: string): Promise<T[]> {
  const res = await axios.get(url);
  if (!Array.isArray(res.data)) {
    // Learned the hard way: axios.get<T[]>()'s generic is compile-time only
    // and does not validate the actual response. Fail loudly here instead of
    // letting bad data reach a .map() call deep in an unrelated component.
    throw new Error(
      `Expected an array from ${url}, got ${typeof res.data}. ` +
      `Check that the file actually exists at this path and was exported ` +
      `by the regression review cell (not overwritten by a later cell).`
    );
  }
  return res.data as T[];
}

export async function loadCoefficientPlot(): Promise<CoefficientPlotRow[]> {
  return fetchValidatedArray<CoefficientPlotRow>(`${DATA_BASE_URL}/regression_coefficient_plot.json`);
}

export async function loadReviewArtifacts(): Promise<ReviewArtifact[]> {
  return fetchValidatedArray<ReviewArtifact>(`${DATA_BASE_URL}/regression_review_artifacts.json`);
}
