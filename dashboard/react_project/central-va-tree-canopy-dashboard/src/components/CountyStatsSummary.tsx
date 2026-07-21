// CountyStatsSummary.tsx
// Numeric summary cards for a county's canopy data -- tile count, mean cover
// (both methods), total trees, and a vegetation-source breakdown. Deliberately
// NOT a chart component (CanopyCoverBar.tsx / TreeCanopyChart.tsx already
// cover that and are being updated separately) -- this is just the
// at-a-glance stat-card row, styled consistently with this dashboard's
// existing green palette and card conventions (see LagLegend.tsx).

import type { CoverRow } from "../lidarData";

interface CountyStatsSummaryProps {
  county: string;
  cover: CoverRow[];
}

export function CountyStatsSummary({ county, cover }: CountyStatsSummaryProps) {
  const tileCount = cover.length;
  const totalTrees = cover.reduce((sum, r) => sum + (r.n_trees || 0), 0);
  const meanFirstReturn = tileCount
    ? cover.reduce((sum, r) => sum + (r.canopy_cover_firstreturn || 0), 0) / tileCount
    : 0;
  const meanChm = tileCount
    ? cover.reduce((sum, r) => sum + (r.canopy_cover_raster || 0), 0) / tileCount
    : 0;

  const vegSourceCounts = cover.reduce<Record<string, number>>((acc, r) => {
    const key = r.veg_source || "n/a";
    acc[key] = (acc[key] || 0) + 1;
    return acc;
  }, {});

  const stats = [
    { label: "Tiles processed", value: tileCount.toLocaleString() },
    { label: "Trees detected", value: totalTrees.toLocaleString() },
    { label: "Mean cover (first-return)", value: `${(meanFirstReturn * 100).toFixed(1)}%` },
    { label: "Mean cover (CHM)", value: `${(meanChm * 100).toFixed(1)}%` },
  ];

  return (
    <section style={{ padding: "1.5rem 2rem", fontFamily: "sans-serif" }}>
      <h2 style={{ color: "#1b4332", marginBottom: "1rem" }}>
        {county} — Canopy Summary
      </h2>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
          gap: "0.75rem",
          marginBottom: "1rem",
        }}
      >
        {stats.map((s) => (
          <div
            key={s.label}
            style={{
              background: "#f1f8f4",
              border: "1px solid #b7e4c7",
              borderRadius: "8px",
              padding: "0.75rem 1rem",
            }}
          >
            <div style={{ fontSize: "0.72rem", color: "#555", textTransform: "uppercase", letterSpacing: "0.03em" }}>
              {s.label}
            </div>
            <div style={{ fontSize: "1.4rem", fontWeight: 700, color: "#1b4332", marginTop: "0.2rem" }}>
              {s.value}
            </div>
          </div>
        ))}
      </div>

      <div style={{ display: "flex", gap: "1rem", fontSize: "0.8rem", color: "#555" }}>
        <span style={{ fontWeight: 600 }}>Vegetation source:</span>
        {Object.entries(vegSourceCounts).map(([source, count]) => (
          <span key={source}>
            {source}: {count} tile{count === 1 ? "" : "s"}
          </span>
        ))}
      </div>
    </section>
  );
}
