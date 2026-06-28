// ─── LagLegend.tsx ───────────────────────────────────────────────────────────
// Renders a vertical color-scale legend for the active choropleth metric.
// Positioned as a Leaflet Control overlay in the bottom-right corner of the map.

import React from "react";
import { type MetricKey, METRIC_META } from "../types";
import { buildLegendStops } from "../colorScale";

interface LagLegendProps {
  metric: MetricKey;
  min: number;
  max: number;
}

/**
 * LagLegend — a pure React component (no Leaflet dependency).
 * Wrap it in a Leaflet <Control> or render it as an absolutely-positioned
 * overlay inside the map container div.
 */
export const LagLegend: React.FC<LagLegendProps> = ({ metric, min, max }) => {
  const meta = METRIC_META[metric];
  const stops = buildLegendStops(min, max, metric, meta.decimals);

  // Build a CSS linear-gradient string from the stops for the gradient bar
  const gradientColors = stops.map((s) => s.color).join(", ");
  const gradient = `linear-gradient(to top, ${gradientColors})`;

  const isLag = metric === "sm_mean_lag1" || metric === "sm_mean_lag2";

  return (
    <div
      style={{
        position: "absolute",
        bottom: "2rem",
        right: "0.75rem",
        zIndex: 1000,
        background: "rgba(255,255,255,0.92)",
        borderRadius: "6px",
        padding: "0.6rem 0.75rem",
        boxShadow: "0 1px 5px rgba(0,0,0,0.3)",
        minWidth: "120px",
        fontFamily: "sans-serif",
        fontSize: "11px",
        color: "#2a3f5f",
        pointerEvents: "none",
      }}
    >
      {/* Title */}
      <div style={{ fontWeight: 700, marginBottom: "0.3rem", lineHeight: 1.3 }}>
        {meta.label}
      </div>

      {/* Lag-specific note */}
      {isLag && (
        <div
          style={{
            fontSize: "10px",
            color: "#666",
            marginBottom: "0.4rem",
            lineHeight: 1.2,
          }}
        >
          Diverging scale:<br />
          orange = low · purple = high
        </div>
      )}

      {/* Gradient bar + tick labels */}
      <div style={{ display: "flex", alignItems: "stretch", gap: "0.4rem" }}>
        {/* Color bar */}
        <div
          style={{
            width: "14px",
            minHeight: "90px",
            background: gradient,
            borderRadius: "3px",
            border: "1px solid #ccc",
            flexShrink: 0,
          }}
        />

        {/* Labels — rendered top to bottom (high → low) */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            justifyContent: "space-between",
            minHeight: "90px",
          }}
        >
          {[...stops].reverse().map((s, i) => (
            <span key={i} style={{ whiteSpace: "nowrap" }}>
              {s.label}
            </span>
          ))}
        </div>
      </div>

      {/* Unit */}
      <div style={{ marginTop: "0.3rem", color: "#888", fontSize: "10px" }}>
        {meta.unit}
      </div>

      {/* No-data swatch */}
      <div style={{ display: "flex", alignItems: "center", gap: "0.3rem", marginTop: "0.4rem" }}>
        <div
          style={{
            width: "14px",
            height: "10px",
            background: "#cccccc",
            border: "1px solid #ccc",
            borderRadius: "2px",
            flexShrink: 0,
          }}
        />
        <span style={{ color: "#888" }}>No data</span>
      </div>
    </div>
  );
};

export default LagLegend;
