// ─── BayesianForecastPanel.tsx ───────────────────────────────────────────────
// Self-contained section combining the static PNG (matplotlib KDE snapshot), 
// the interactive trend chart (median + credible interval), and the
// decline-risk bar chart -- following the same pattern as LidarCanopyPanel.tsx
// (own state, own fetching, drops into App.tsx as a single line). 

import { useEffect, useMemo, useState } from "react";
import { loadForecastTrend, loadRiskSummary, forecastImageUrl } from "../bayesianData";
import type { BayesianMetric, TrendRow, RiskRow } from "../bayesianData";
import { BayesianForecastTrendChart } from "./BayesianForecastTrendChart";
import { BayesianRiskSummaryChart } from "./BayesianRiskSummaryChart";

const METRIC_LABELS: Record<BayesianMetric, string> = {
  height: "Canopy Height (m)",
  cover: "Canopy Cover (fraction)",
};

export default function BayesianForecastPanel() {
  const [metric, setMetric] = useState<BayesianMetric>("height");
  const [trend, setTrend] = useState<TrendRow[]>([]);
  const [risk, setRisk] = useState<RiskRow[]>([]);
  const [jurisdiction, setJurisdiction] = useState<string | null>(null);
  const [riskYear, setRiskYear] = useState<2027 | 2028>(2027);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showImage, setShowImage] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    Promise.all([loadForecastTrend(metric), loadRiskSummary(metric)])
      .then(([trendData, riskData]) => {
        if (cancelled) return;
        setTrend(trendData);
        setRisk(riskData);
        const firstJuris = [...new Set(trendData.map((r) => r.jurisdiction))][0];
        setJurisdiction(firstJuris ?? null);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [metric]);

  const jurisdictions = useMemo(
    () => [...new Set(trend.map((r) => r.jurisdiction))],
    [trend]
  );

  return (
    <section style={{ padding: "1.5rem 2rem", fontFamily: "sans-serif" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "1rem" }}>
        <h2 style={{ color: "#1b4332", margin: 0 }}>Bayesian Canopy Forecast</h2>

        <div style={{ display: "flex", gap: "1rem", alignItems: "center", fontSize: "0.85rem" }}>
          <label>
            Metric:{" "}
            <select value={metric} onChange={(e) => setMetric(e.target.value as BayesianMetric)}
              style={{ padding: "0.3rem 0.5rem", borderRadius: "4px", border: "1px solid #ccc" }}>
              <option value="height">Canopy Height</option>
              <option value="cover">Canopy Cover</option>
            </select>
          </label>

          {jurisdictions.length > 0 && (
            <label>
              Jurisdiction:{" "}
              <select value={jurisdiction ?? ""} onChange={(e) => setJurisdiction(e.target.value)}
                style={{ padding: "0.3rem 0.5rem", borderRadius: "4px", border: "1px solid #ccc" }}>
                {jurisdictions.map((j) => (
                  <option key={j} value={j}>{j}</option>
                ))}
              </select>
            </label>
          )}

          <label>
            Risk year:{" "}
            <select value={riskYear} onChange={(e) => setRiskYear(Number(e.target.value) as 2027 | 2028)}
              style={{ padding: "0.3rem 0.5rem", borderRadius: "4px", border: "1px solid #ccc" }}>
              <option value={2027}>2027</option>
              <option value={2028}>2028</option>
            </select>
          </label>

          <label style={{ cursor: "pointer" }}>
            <input type="checkbox" checked={showImage} onChange={(e) => setShowImage(e.target.checked)} />{" "}
            Show KDE snapshot image
          </label>
        </div>
      </div>

      {loading && <p style={{ color: "#555" }}>Loading Bayesian forecast data…</p>}
      {error && (
        <p style={{ color: "#b02a2a" }}>
          Couldn't load Bayesian forecast data: {error}
          <br />
          Confirm the pipeline was run with <code>--upload-to-dashboard</code>.
        </p>
      )}

      {!loading && !error && (
        <>
          {showImage && (
            <div style={{ marginBottom: "1.25rem", textAlign: "center" }}>
              <img
                src={forecastImageUrl(metric)}
                alt={`${METRIC_LABELS[metric]} forecast KDE snapshot`}
                style={{ maxWidth: "100%", borderRadius: "8px", border: "1px solid #b7e4c7" }}
              />
            </div>
          )}

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1.5rem" }}>
            {jurisdiction && trend.length > 0 && (
              <BayesianForecastTrendChart
                trend={trend}
                jurisdiction={jurisdiction}
                metricLabel={METRIC_LABELS[metric]}
              />
            )}
            {risk.length > 0 && (
              <BayesianRiskSummaryChart
                risk={risk}
                year={riskYear}
                metricLabel={METRIC_LABELS[metric]}
              />
            )}
          </div>
        </>
      )}
    </section>
  );
}
