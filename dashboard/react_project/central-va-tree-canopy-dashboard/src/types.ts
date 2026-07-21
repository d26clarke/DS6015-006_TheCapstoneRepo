// ─── types.ts ────────────────────────────────────────────────────────────────
// Shared TypeScript interfaces for the SMAP + GEDI split-panel dashboard.
//
// NOTE: previously this file had two parallel metric systems
// (MetricGedi02AKey/META and MetricGedi02BKey/META) mirroring the two
// source datasets. That parallel structure is what invited the copy-paste
// bugs in SplitPanelDashboard.tsx (canopy height treated as a 0-1 fraction,
// wrong "%" unit, etc.) -- folding them into one MetricKey/METRIC_META below
// removes the second, easy-to-desync copy entirely.

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

/** One row from merged_smap_gedi.json — GEDI Level 2A canopy HEIGHT, per jurisdiction */
export interface MergedGedi02ARow {
  year: number;
  jurisdiction: string;
  canopy_height_mean_m: number;    // GEDI Level 2A mean canopy height, in METERS (not a 0-1 fraction)
  sm_mean_m3m3: number;
  sm_min: number;
  sm_max: number;
  sm_std: number;
  sm_mean_lag1: number | null;
  sm_mean_lag2: number | null;
}

/** One row from merged_smap_gedi02B.json — GEDI Level 2B canopy COVER, per jurisdiction */
export interface MergedGedi02BRow {
  jurisdiction: string;
  year: number;
  mean_canopy_cover: number;       // GEDI Level 2B canopy cover fraction (0–1)
  total_valid_shots: number;
  sm_mean_m3m3: number;
  sm_min: number;
  sm_max: number;
  sm_std: number;
  sm_mean_lag1: number | null;
  sm_mean_lag2: number | null;
}

/** Combined per-jurisdiction/year record, merging 02A + 02B on (jurisdiction, year).
 *  Fields are null where that source doesn't have a row for this combination
 *  (e.g. Buckingham has 02A height data but no 02B cover data). */
export interface CombinedRow {
  jurisdiction: string;
  year: number;
  canopy_height_mean_m: number | null;
  mean_canopy_cover: number | null;
  sm_mean_m3m3: number | null;
  sm_mean_lag1: number | null;
  sm_mean_lag2: number | null;
}

/** Single unified metric key -- covers height, cover, and soil moisture (same-year + both lags) */
export type MetricKey =
  | "canopy_height_mean_m"
  | "mean_canopy_cover"
  | "sm_mean_m3m3"
  | "sm_mean_lag1"
  | "sm_mean_lag2";

/** Human-readable labels, units, and decimal precision for each metric.
 *  Units are per-metric on purpose: height is meters, cover is a percentage,
 *  soil moisture is m³/m³ -- these should never share a color/axis scale
 *  or a "multiply by 100" transform, which was the root cause of the
 *  Canopy Height chart bug. */
export const METRIC_META: Record<MetricKey, { label: string; unit: string; decimals: number }> = {
  canopy_height_mean_m: { label: "Canopy Height",           unit: "m",      decimals: 1 },
  mean_canopy_cover:     { label: "Canopy Cover",            unit: "%",      decimals: 1 },
  sm_mean_m3m3:          { label: "Soil Moisture (same yr)", unit: "m³/m³",  decimals: 4 },
  sm_mean_lag1:          { label: "Soil Moisture (1-yr lag)",unit: "m³/m³",  decimals: 4 },
  sm_mean_lag2:          { label: "Soil Moisture (2-yr lag)",unit: "m³/m³",  decimals: 4 },
};

/** Available years in the merged dataset */
export const AVAILABLE_YEARS = [2019, 2020, 2021, 2022, 2023] as const;
export type AvailableYear = typeof AVAILABLE_YEARS[number];
