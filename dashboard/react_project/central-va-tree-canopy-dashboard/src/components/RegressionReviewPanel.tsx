// ─── RegressionReviewPanel.tsx ───────────────────────────────────────────────
// Self-contained section: loads both regression review artifacts, shows the
// coefficient chart (canopy height vs. cover selectable) plus the full
// review-artifact cards below. Same pattern as LidarCanopyPanel.tsx /
// BayesianForecastPanel.tsx -- own state, own fetching, drops into App.tsx
// as a single line.

import { useEffect, useState } from "react";
import { loadCoefficientPlot, loadReviewArtifacts } from "../regressionData";
import type { CoefficientPlotRow, ReviewArtifact } from "../regressionData";
import { RegressionCoefficientChart } from "./RegressionCoefficientChart";
import { RegressionReviewTable } from "./RegressionReviewTable";

export default function RegressionReviewPanel() {
  const [coefRows, setCoefRows] = useState<CoefficientPlotRow[]>([]);
  const [reviewRows, setReviewRows] = useState<ReviewArtifact[]>([]);
  const [canopyVar, setCanopyVar] = useState<string>("mean_canopy_cover");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filterUntrustworthyOnly, setFilterUntrustworthyOnly] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    Promise.all([loadCoefficientPlot(), loadReviewArtifacts()])
      .then(([coef, review]) => {
        if (cancelled) return;
        setCoefRows(coef);
        setReviewRows(review);
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
  }, []);

  const canopyVars = [...new Set(coefRows.map((r) => r.canopy_var))];

  const displayedReviewRows = filterUntrustworthyOnly
    ? reviewRows.filter((r) => {
        const match = coefRows.find((c) => c.outcome === r.outcome && c.canopy_var === r.canopy_var);
        return match ? !match.trustworthy : true;
      })
    : reviewRows;

  return (
    <section style={{ padding: "1.5rem 2rem", fontFamily: "sans-serif" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "1rem", flexWrap: "wrap", gap: "0.5rem" }}>
        <div>
          <h2 style={{ color: "#1b4332", margin: 0 }}>Multivariate Regression — Review Artifacts</h2>
          <p style={{ fontSize: "0.78rem", color: "#666", margin: "0.2rem 0 0" }}>
            Canopy cover / height vs. K-12 SOL, crime, and CDC PLACES health outcomes.
            Every result below has been checked for leverage, multicollinearity, and
            (for panel models) sensitivity to clustered vs. robust standard errors before
            being surfaced here — internal team review, not a final policy claim.
          </p>
        </div>

        <div style={{ display: "flex", gap: "1rem", alignItems: "center", fontSize: "0.85rem" }}>
          {canopyVars.length > 0 && (
            <label>
              Canopy metric:{" "}
              <select value={canopyVar} onChange={(e) => setCanopyVar(e.target.value)}
                style={{ padding: "0.3rem 0.5rem", borderRadius: "4px", border: "1px solid #ccc" }}>
                {canopyVars.map((cv) => (
                  <option key={cv} value={cv}>{cv === "mean_canopy_cover" ? "Canopy Cover" : "Canopy Height"}</option>
                ))}
              </select>
            </label>
          )}
          <label style={{ cursor: "pointer" }}>
            <input type="checkbox" checked={filterUntrustworthyOnly} onChange={(e) => setFilterUntrustworthyOnly(e.target.checked)} />{" "}
            Flagged results only
          </label>
        </div>
      </div>

      {loading && <p style={{ color: "#555" }}>Loading regression review artifacts…</p>}
      {error && (
        <p style={{ color: "#b02a2a" }}>
          Couldn't load regression review data: {error}
        </p>
      )}

      {!loading && !error && (
        <>
          {coefRows.length > 0 && (
            <div style={{ marginBottom: "1.5rem" }}>
              <RegressionCoefficientChart rows={coefRows} canopyVar={canopyVar} />
            </div>
          )}
          {displayedReviewRows.length > 0 ? (
            <RegressionReviewTable rows={displayedReviewRows.filter((r) => r.canopy_var === canopyVar)} />
          ) : (
            <p style={{ color: "#666", fontSize: "0.85rem" }}>No flagged results for this canopy metric.</p>
          )}
        </>
      )}
    </section>
  );
}
