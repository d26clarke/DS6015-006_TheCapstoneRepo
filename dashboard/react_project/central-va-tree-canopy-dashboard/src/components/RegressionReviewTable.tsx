// ─── RegressionReviewTable.tsx ───────────────────────────────────────────────
// The actual approve/deny artifact: one expandable card per regression result,
// showing the plain-language recommendation and confidence flags up front,
// with full underlying diagnostics (VIF, leverage, Cook's distance,
// leave-one-out sensitivity) available on demand -- not hidden, but not
// forced on a reviewer who just wants the verdict.

import { useState } from "react";
import type { ReviewArtifact } from "../regressionData";

function recommendationColor(rec: string): string {
  if (rec.startsWith("Do NOT use")) return "#c0392b";
  if (rec.startsWith("Statistically significant")) return "#2d6a4f";
  if (rec.startsWith("Not estimable")) return "#888";
  return "#555"; // "Not statistically significant..."
}

function flagColor(flag: string): { bg: string; fg: string } {
  if (flag.startsWith("NOT_robust") || flag.startsWith("small_sample") || flag.startsWith("near_saturated")) {
    return { bg: "#fdecea", fg: "#c0392b" };
  }
  if (flag.startsWith("robust_to") || flag === "no_major_concerns_detected") {
    return { bg: "#eaf7ee", fg: "#2d6a4f" };
  }
  return { bg: "#fff6e5", fg: "#8a6416" }; // informational (few_clusters, influential_point, VIF, etc.)
}

function ReviewCard({ row }: { row: ReviewArtifact }) {
  const [expanded, setExpanded] = useState(false);
  const d = row.diagnostics;

  return (
    <div style={{ border: "1px solid #ddd", borderRadius: "8px", marginBottom: "0.75rem", overflow: "hidden" }}>
      <div style={{ padding: "0.75rem 1rem", background: "#f8faf8" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", flexWrap: "wrap", gap: "0.5rem" }}>
          <div>
            <strong style={{ fontSize: "0.95rem" }}>{row.outcome}</strong>
            <span style={{ color: "#666", fontSize: "0.8rem" }}> ~ {row.canopy_var} ({row.model_type})</span>
          </div>
          <div style={{ fontSize: "0.8rem", fontFamily: "monospace" }}>
            beta={row.beta} &nbsp; p={row.p_value} &nbsp; n={row.n_obs}
          </div>
        </div>

        <div style={{ marginTop: "0.4rem", fontSize: "0.85rem", fontWeight: 600, color: recommendationColor(row.reviewer_recommendation) }}>
          {row.reviewer_recommendation}
        </div>

        <div style={{ marginTop: "0.5rem", display: "flex", flexWrap: "wrap", gap: "0.35rem" }}>
          {row.confidence_flags.map((flag, i) => {
            const c = flagColor(flag);
            return (
              <span key={i} style={{ background: c.bg, color: c.fg, borderRadius: "4px", padding: "0.15rem 0.5rem", fontSize: "0.72rem" }}>
                {flag}
              </span>
            );
          })}
        </div>

        {d && (
          <button
            onClick={() => setExpanded((e) => !e)}
            style={{ marginTop: "0.6rem", fontSize: "0.75rem", background: "none", border: "1px solid #bbb", borderRadius: "4px", padding: "0.25rem 0.6rem", cursor: "pointer" }}
          >
            {expanded ? "Hide diagnostics" : "Show diagnostics"}
          </button>
        )}
      </div>

      {expanded && d && (
        <div style={{ padding: "0.75rem 1rem", fontSize: "0.78rem", background: "#fff", borderTop: "1px solid #eee" }}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: "0.5rem", marginBottom: "0.6rem" }}>
            <div><strong>n_obs:</strong> {d.n_obs}</div>
            {d.n_params !== undefined && <div><strong>n_params:</strong> {d.n_params}</div>}
            {d.residual_df !== undefined && <div><strong>residual_df:</strong> {d.residual_df}</div>}
            {d.n_clusters !== undefined && <div><strong>n_clusters:</strong> {d.n_clusters}</div>}
          </div>

          {d.max_hat !== undefined && (
            <div style={{ marginBottom: "0.4rem" }}>
              <strong>Leverage:</strong> max hat = {d.max_hat} ({d.max_hat_jurisdiction}), mean hat = {d.mean_hat}
            </div>
          )}
          {d.max_cooks_d !== undefined && (
            <div style={{ marginBottom: "0.4rem" }}>
              <strong>Cook's distance:</strong> max = {d.max_cooks_d} ({d.max_cooks_d_jurisdiction}), threshold = {d.cooks_d_threshold}
            </div>
          )}
          {d.vif && (
            <div style={{ marginBottom: "0.4rem" }}>
              <strong>VIF:</strong>{" "}
              {Object.entries(d.vif).map(([k, v]) => `${k}=${v}`).join(", ")}
            </div>
          )}
          {d.leave_one_out && (
            <div style={{ marginBottom: "0.4rem" }}>
              <strong>Leave-one-out</strong> (excluding {d.leave_one_out.excluded_jurisdiction}):{" "}
              n={d.leave_one_out.n_obs}, beta={d.leave_one_out.beta}, p={d.leave_one_out.p_value}, R²={d.leave_one_out.r_squared}
            </div>
          )}
          {d.p_value_clustered !== undefined && (
            <div style={{ marginBottom: "0.4rem" }}>
              <strong>Clustered vs. robust SE:</strong> p (clustered) = {d.p_value_clustered}, p (robust, unclustered) = {d.p_value_robust_unclustered}
              {d.min_recommended_clusters !== undefined && (
                <> &nbsp;(min recommended clusters: {d.min_recommended_clusters})</>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

interface RegressionReviewTableProps {
  rows: ReviewArtifact[];
}

export function RegressionReviewTable({ rows }: RegressionReviewTableProps) {
  return (
    <div>
      <h3 style={{ fontSize: "0.95rem", color: "#1b4332", margin: "0 0 0.6rem" }}>
        Regression Review Artifacts
      </h3>
      {rows.map((row, i) => (
        <ReviewCard key={i} row={row} />
      ))}
    </div>
  );
}
