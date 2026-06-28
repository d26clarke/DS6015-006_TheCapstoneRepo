// ─── colorScale.ts ───────────────────────────────────────────────────────────
// Utility functions for mapping numeric values to choropleth fill colors
// and generating the color scale legend for lag fields.

import { type MetricKey } from "./types";

// ── Color ramps ──────────────────────────────────────────────────────────────
// Each ramp is defined as [stop_0_to_1, hex_color] pairs.
// Canopy cover uses a green ramp (low = pale, high = forest green).
// Soil moisture (same-year and lags) uses a blue ramp.
// Lag fields get a diverging blue-orange ramp to visually distinguish them
// from the same-year soil moisture.

type ColorStop = [number, string];

const GREEN_RAMP: ColorStop[] = [
  [0.0,  "#f7fcf5"],
  [0.2,  "#c7e9c0"],
  [0.4,  "#74c476"],
  [0.6,  "#31a354"],
  [0.8,  "#006d2c"],
  [1.0,  "#00441b"],
];

const BLUE_RAMP: ColorStop[] = [
  [0.0,  "#f7fbff"],
  [0.2,  "#c6dbef"],
  [0.4,  "#6baed6"],
  [0.6,  "#2171b5"],
  [0.8,  "#08519c"],
  [1.0,  "#08306b"],
];

// Diverging blue-orange for lag fields (low lag SM = orange, high = blue)
const LAG_RAMP: ColorStop[] = [
  [0.0,  "#b35806"],
  [0.2,  "#f1a340"],
  [0.4,  "#fee0b6"],
  [0.6,  "#d8daeb"],
  [0.8,  "#998ec3"],
  [1.0,  "#542788"],
];

/** Select the appropriate color ramp for a given metric */
function rampForMetric(metric: MetricKey): ColorStop[] {
  if (metric === "mean_canopy_cover") return GREEN_RAMP;
  if (metric === "sm_mean_m3m3")      return BLUE_RAMP;
  return LAG_RAMP; // sm_mean_lag1, sm_mean_lag2
}

/** Linearly interpolate between two hex colors */
function lerpHex(a: string, b: string, t: number): string {
  const parse = (h: string) => [
    parseInt(h.slice(1, 3), 16),
    parseInt(h.slice(3, 5), 16),
    parseInt(h.slice(5, 7), 16),
  ];
  const [ar, ag, ab] = parse(a);
  const [br, bg, bb] = parse(b);
  const r = Math.round(ar + (br - ar) * t);
  const g = Math.round(ag + (bg - ag) * t);
  const bv = Math.round(ab + (bb - ab) * t);
  return `#${r.toString(16).padStart(2, "0")}${g.toString(16).padStart(2, "0")}${bv.toString(16).padStart(2, "0")}`;
}

/**
 * Map a normalized value (0–1) to a hex color using the given ramp.
 */
function sampleRamp(ramp: ColorStop[], t: number): string {
  const clamped = Math.max(0, Math.min(1, t));
  for (let i = 0; i < ramp.length - 1; i++) {
    const [t0, c0] = ramp[i];
    const [t1, c1] = ramp[i + 1];
    if (clamped >= t0 && clamped <= t1) {
      const localT = (clamped - t0) / (t1 - t0);
      return lerpHex(c0, c1, localT);
    }
  }
  return ramp[ramp.length - 1][1];
}

/**
 * Given a value, the domain [min, max], and the metric key,
 * return the choropleth fill color as a hex string.
 * Returns "#cccccc" for null/undefined values.
 */
export function valueToColor(
  value: number | null | undefined,
  min: number,
  max: number,
  metric: MetricKey
): string {
  if (value == null || isNaN(value)) return "#cccccc";
  const t = max === min ? 0.5 : (value - min) / (max - min);
  return sampleRamp(rampForMetric(metric), t);
}

/**
 * Generate an array of { color, label } stops for the legend component.
 * Returns 6 evenly-spaced stops between min and max.
 */
export function buildLegendStops(
  min: number,
  max: number,
  metric: MetricKey,
  decimals: number
): { color: string; label: string }[] {
  const ramp = rampForMetric(metric);
  const steps = 6;
  return Array.from({ length: steps }, (_, i) => {
    const t = i / (steps - 1);
    const value = min + t * (max - min);
    return {
      color: sampleRamp(ramp, t),
      label: metric === "mean_canopy_cover"
        ? `${(value * 100).toFixed(decimals)}%`
        : value.toFixed(decimals),
    };
  });
}

/** Compute the [min, max] domain for a metric across a filtered dataset */
export function computeDomain(
  rows: { [key: string]: any }[],
  metric: MetricKey
): [number, number] {
  const values = rows
    .map((r) => r[metric] as number | null)
    .filter((v): v is number => v != null && !isNaN(v));
  if (values.length === 0) return [0, 1];
  return [Math.min(...values), Math.max(...values)];
}
