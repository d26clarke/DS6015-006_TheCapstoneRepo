// ─── BayesianForecastTrendChart.tsx ──────────────────────────────────────────
// Median + 95% credible interval band per scenario, across the full forecast
// horizon, for a single selected jurisdiction. Complements the static PNG 
// (which shows 2027/2028 KDE snapshots only) with the full year-by-year trend.

import {
  ComposedChart,
  Area,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import type { TrendRow } from "../bayesianData";

const SCENARIO_COLORS: Record<string, string> = {
  "Severe Drought": "#e66101",
  "Climate Recovery": "#5e3c99",
};

interface BayesianForecastTrendChartProps {
  trend: TrendRow[];
  jurisdiction: string;
  metricLabel: string;
}

export function BayesianForecastTrendChart({
  trend,
  jurisdiction,
  metricLabel,
}: BayesianForecastTrendChartProps) {
  const juriRows = trend.filter((r) => r.jurisdiction === jurisdiction);
  const scenarios = [...new Set(juriRows.map((r) => r.scenario))];
  const years = [...new Set(juriRows.map((r) => r.year))].sort((a, b) => a - b);

  // Pivot into one row per year, with a [low, high] range + median per scenario,
  // since Recharts renders a two-value array as a filled band directly.
  const chartData = years.map((year) => {
    const row: Record<string, number | number[] | string> = { year };
    scenarios.forEach((scen) => {
      const match = juriRows.find((r) => r.scenario === scen && r.year === year);
      if (match) {
        row[`${scen}__range`] = [match.p2_5, match.p97_5];
        row[`${scen}__median`] = match.median;
      }
    });
    return row;
  });

  return (
    <div>
      <h3 style={{ fontSize: "0.95rem", color: "#1b4332", margin: "0 0 0.5rem" }}>
        {jurisdiction} — {metricLabel} Forecast (median + 95% credible interval)
      </h3>
      <ResponsiveContainer width="100%" height={280}>
        <ComposedChart data={chartData} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e0e0e0" />
          <XAxis dataKey="year" tick={{ fontSize: 11 }} />
          <YAxis tick={{ fontSize: 11 }} width={48} />
          <Tooltip formatter={(v) => (Array.isArray(v) ? v.map((n) => n.toFixed(2)).join(" – ") : (v as number).toFixed(2))} />
          <Legend />
          {scenarios.map((scen) => (
            <Area
              key={`${scen}__range`}
              dataKey={`${scen}__range`}
              name={`${scen} (95% CI)`}
              stroke="none"
              fill={SCENARIO_COLORS[scen] ?? "#888"}
              fillOpacity={0.18}
              isAnimationActive={false}
            />
          ))}
          {scenarios.map((scen) => (
            <Line
              key={`${scen}__median`}
              type="monotone"
              dataKey={`${scen}__median`}
              name={`${scen} (median)`}
              stroke={SCENARIO_COLORS[scen] ?? "#888"}
              strokeWidth={2.5}
              dot={{ r: 3 }}
              connectNulls
            />
          ))}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
