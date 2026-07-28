// ─── RegressionCoefficientChart.tsx ──────────────────────────────────────────
// Forest-plot-style bar chart of canopy coefficients (beta) per outcome,
// split by canopy variable (height vs. cover). Color-coded by TRUSTWORTHINESS
// first, significance second -- deliberately, since the whole point of this
// pipeline is that "significant" and "trustworthy" are NOT the same thing
// (e.g. the Diabetes finding: p=0.0000 but flagged do-not-use).

import {
  BarChart,
  Bar,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
} from "recharts";
import type { CoefficientPlotRow } from "../regressionData";

const COLOR_TRUSTWORTHY_SIGNIFICANT = "#2d6a4f";
const COLOR_TRUSTWORTHY_NOT_SIGNIFICANT = "#94a3b8";
const COLOR_NOT_TRUSTWORTHY = "#c0392b";

function barColor(row: CoefficientPlotRow): string {
  if (!row.trustworthy) return COLOR_NOT_TRUSTWORTHY;
  return row.significant ? COLOR_TRUSTWORTHY_SIGNIFICANT : COLOR_TRUSTWORTHY_NOT_SIGNIFICANT;
}

interface RegressionCoefficientChartProps {
  rows: CoefficientPlotRow[];
  canopyVar: string;
  onSelectBar?: (row: CoefficientPlotRow) => void;
}

export function RegressionCoefficientChart({ rows, canopyVar, onSelectBar }: RegressionCoefficientChartProps) {
  const filtered = rows.filter((r) => r.canopy_var === canopyVar);

  const chartData = filtered.map((r) => ({
    ...r,
    label: r.outcome,
  }));

  return (
    <div>
      <h3 style={{ fontSize: "0.95rem", color: "#1b4332", margin: "0 0 0.25rem" }}>
        Canopy Coefficient by Outcome — {canopyVar === "mean_canopy_cover" ? "Canopy Cover" : "Canopy Height"}
      </h3>
      <p style={{ fontSize: "0.75rem", color: "#666", margin: "0 0 0.5rem" }}>
        Color reflects trustworthiness, not just statistical significance — a red bar can still show p &lt; 0.05.
      </p>
      <ResponsiveContainer width="100%" height={Math.max(220, filtered.length * 55)}>
        <BarChart data={chartData} layout="vertical" margin={{ top: 5, right: 30, left: 10, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e0e0e0" />
          <XAxis type="number" tick={{ fontSize: 11 }} />
          <YAxis type="category" dataKey="label" width={160} tick={{ fontSize: 11 }} />
          <ReferenceLine x={0} stroke="#888" />
          <Tooltip
            content={({ active, payload }) => {
              if (!active || !payload || !payload.length) return null;
              const row = payload[0].payload as CoefficientPlotRow & { label: string };
              return (
                <div style={{ background: "#fff", border: "1px solid #ccc", borderRadius: "6px", padding: "0.5rem 0.75rem", fontSize: "0.78rem" }}>
                  <strong>{row.outcome}</strong>
                  <div>beta: {row.beta}</div>
                  <div>p-value: {row.p_value}</div>
                  <div>n_obs: {row.n_obs}</div>
                  <div>model: {row.model_type}</div>
                  <div style={{ marginTop: "0.3rem", color: row.trustworthy ? "#2d6a4f" : "#c0392b", fontWeight: 600 }}>
                    {row.trustworthy ? "No blocking concerns" : `${row.flag_count} flag(s) raised`}
                  </div>
                </div>
              );
            }}
          />
          <Bar
            dataKey="beta"
            onClick={(data) => onSelectBar?.(data as unknown as CoefficientPlotRow)}
            cursor={onSelectBar ? "pointer" : undefined}
          >
            {chartData.map((row, i) => (
              <Cell key={i} fill={barColor(row)} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <div style={{ display: "flex", gap: "1rem", fontSize: "0.72rem", marginTop: "0.4rem", color: "#555" }}>
        <span><span style={{ display: "inline-block", width: 10, height: 10, background: COLOR_TRUSTWORTHY_SIGNIFICANT, marginRight: 4 }} />Trustworthy &amp; significant</span>
        <span><span style={{ display: "inline-block", width: 10, height: 10, background: COLOR_TRUSTWORTHY_NOT_SIGNIFICANT, marginRight: 4 }} />Trustworthy, not significant</span>
        <span><span style={{ display: "inline-block", width: 10, height: 10, background: COLOR_NOT_TRUSTWORTHY, marginRight: 4 }} />Flagged -- do not use</span>
      </div>
    </div>
  );
}
