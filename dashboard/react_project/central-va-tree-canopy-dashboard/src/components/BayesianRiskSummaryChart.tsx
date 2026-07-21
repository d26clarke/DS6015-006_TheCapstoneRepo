// ─── BayesianRiskSummaryChart.tsx ────────────────────────────────────────────
// Bar chart of decline-risk probability (%) by jurisdiction, one bar per
// scenario, for a selected forecast year (2027 or 2028). 

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import type { RiskRow } from "../bayesianData";

const SCENARIO_COLORS: Record<string, string> = {
  "Severe Drought": "#e66101",
  "Climate Recovery": "#5e3c99",
};

interface BayesianRiskSummaryChartProps {
  risk: RiskRow[];
  year: 2027 | 2028;
  metricLabel: string;
}

export function BayesianRiskSummaryChart({ risk, year, metricLabel }: BayesianRiskSummaryChartProps) {
  const riskKey = year === 2027 ? "2027 Decline Risk (%)" : "2028 Decline Risk (%)";
  const jurisdictions = [...new Set(risk.map((r) => r.Jurisdiction))];
  const scenarios = [...new Set(risk.map((r) => r.Scenario))];

  const chartData = jurisdictions.map((j) => {
    const row: Record<string, number | string> = { jurisdiction: j };
    scenarios.forEach((scen) => {
      const match = risk.find((r) => r.Jurisdiction === j && r.Scenario === scen);
      if (match) row[scen] = match[riskKey];
    });
    return row;
  });

  return (
    <div>
      <h3 style={{ fontSize: "0.95rem", color: "#1b4332", margin: "0 0 0.5rem" }}>
        {metricLabel} — Probability of Decline Below Baseline by {year}
      </h3>
      <ResponsiveContainer width="100%" height={280}>
        <BarChart data={chartData} margin={{ top: 5, right: 20, left: 0, bottom: 40 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e0e0e0" />
          <XAxis dataKey="jurisdiction" tick={{ fontSize: 10 }} angle={-45} textAnchor="end" interval={0} />
          <YAxis domain={[0, 100]} tickFormatter={(v) => `${v}%`} tick={{ fontSize: 11 }} width={44} />
          <Tooltip formatter={(v) => `${v}%`} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          {scenarios.map((scen) => (
            <Bar key={scen} dataKey={scen} fill={SCENARIO_COLORS[scen] ?? "#888"} radius={[3, 3, 0, 0]} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
