// ─── types.ts ────────────────────────────────────────────────────────────────
// Shared TypeScript interfaces for the SMAP + GEDI split-panel dashboard.

/** One row from smap_timeseries.json — purely temporal, region-wide aggregate */
export interface SmapRow {
  year: number;
  n_files: number;
  n_valid_days: number;
  n_pixels: number;
  sm_mean: number;
  sm_min: number;
  sm_max: number;
  sm_std: number;
}

/** One row from merged_smap_gedi02B.json — spatiotemporal, per-jurisdiction */
export interface MergedRow {
  jurisdiction: string;
  year: number;
  mean_canopy_cover: number;       // GEDI Level 2B canopy cover fraction (0–1)
  total_valid_shots: number;       // GEDI shot count
  sm_mean_m3m3: number;            // SMAP soil moisture m³/m³ (same year)
  sm_min: number;
  sm_max: number;
  sm_std: number;
  sm_mean_lag1: number | null;     // SMAP soil moisture 1-year lag
  sm_mean_lag2: number | null;     // SMAP soil moisture 2-year lag
}

/** Supported choropleth metric keys */
export type MetricKey =
  | "mean_canopy_cover"
  | "sm_mean_m3m3"
  | "sm_mean_lag1"
  | "sm_mean_lag2";

/** Human-readable labels and units for each metric */
export const METRIC_META: Record<MetricKey, { label: string; unit: string; decimals: number }> = {
  mean_canopy_cover: { label: "Canopy Cover",          unit: "%",       decimals: 1 },
  sm_mean_m3m3:      { label: "Soil Moisture (same yr)",unit: "m³/m³",  decimals: 4 },
  sm_mean_lag1:      { label: "Soil Moisture (1-yr lag)",unit: "m³/m³", decimals: 4 },
  sm_mean_lag2:      { label: "Soil Moisture (2-yr lag)",unit: "m³/m³", decimals: 4 },
};

/** Available years in the merged dataset */
export const AVAILABLE_YEARS = [2019, 2020, 2021, 2022, 2023] as const;
export type AvailableYear = typeof AVAILABLE_YEARS[number];
