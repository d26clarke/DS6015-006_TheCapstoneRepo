// ─── ChmHeightLegend.tsx ─────────────────────────────────────────────────────
// Continuous-scale legend for the CHM raster layer. Styled to match
// LagLegend.tsx's card treatment (same background, radius, shadow, font
// sizes) so it reads as part of the same legend system, but positioned
// bottom-LEFT since LagLegend already occupies bottom-right whenever a
// choropleth metric is also active.

import React from "react";
import { heightToColor, MIN_CANOPY_HEIGHT_M, MAX_CANOPY_HEIGHT_M } from "./ChmRasterLayer";

interface ChmHeightLegendProps {
  maxHeight?: number;
}

export const ChmHeightLegend: React.FC<ChmHeightLegendProps> = ({
  maxHeight = MAX_CANOPY_HEIGHT_M,
}) => {
  const stopCount = 6;
  const stops = Array.from({ length: stopCount }, (_, i) => {
    const h = (maxHeight * i) / (stopCount - 1);
    return { height: h, color: heightToColor(h, maxHeight) };
  });
  const gradient = `linear-gradient(to top, ${stops.map((s) => s.color).join(", ")})`;

  return (
    <div
      style={{
        position: "absolute",
        bottom: "2rem",
        left: "0.75rem",
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
      <div style={{ fontWeight: 700, marginBottom: "0.3rem" }}>Canopy Height (LiDAR)</div>

      <div style={{ display: "flex", alignItems: "stretch", gap: "0.4rem" }}>
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
              {s.height.toFixed(0)}m
            </span>
          ))}
        </div>
      </div>

      <div style={{ marginTop: "0.3rem", color: "#888", fontSize: "10px" }}>
        threshold ≥ {MIN_CANOPY_HEIGHT_M}m
      </div>
    </div>
  );
};

export default ChmHeightLegend;
