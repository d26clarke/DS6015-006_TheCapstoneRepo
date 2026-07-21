// ─── AoiTimeSeriesPanel.tsx ───────────────────────────────────────────────────
//
// Sub-jurisdictional Area-of-Interest (AOI) time-series panel.
//
// Displays canopy height (m) and soil moisture (m³/m³) over time for one of
// three pre-defined AOI datasets:
//   • Route 29 North corridor  (Albemarle only, 2019–2023)
//   • Rivanna Watershed        (all 8 jurisdictions, 2019–2023)
//   • Riverview Park           (Charlottesville only, 2021–2022)
//
// The component is fully independent of SplitPanelDashboard — it shares no
// state and can be placed on a separate tab, route, or below the split panel.
//
// Props:
//   initialDataset  — which AOI to show on first render (default: "rwatershed")
//
// Data contract:
//   AoiRow (see types.ts additions below) — uses canopy_height_mean_m, NOT
//   mean_canopy_cover, so it is intentionally separate from MergedRow.
//
// Dependencies (already in package.json if SplitPanelDashboard is installed):
//   recharts, axios
//
// ─────────────────────────────────────────────────────────────────────────────

import React, { useEffect, useState, useCallback } from "react";
import axios from "axios";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  ReferenceLine,
  Brush,
} from "recharts";

import DATA_BASE_URL from "../config";

// ── AOI-specific types (add these to types.ts as well) ───────────────────────
export interface AoiRow {
  year:                 number;
  jurisdiction:         string;
  canopy_height_mean_m: number | null;
  sm_mean_m3m3:         number | null;
  sm_min:               number | null;
  sm_max:               number | null;
  sm_std:               number | null;
  sm_mean_lag1:         number | null;
  sm_mean_lag2:         number | null;
}

export type AoiDatasetKey = "route29north" | "rwatershed" | "rviewpark";

export const AOI_DATASET_META: Record<
  AoiDatasetKey,
  { label: string; s3Key: string; description: string }
> = {
  route29north: {
    label:       "Route 29 North Corridor",
    s3Key:       "merged_smap_gedi-route29north.json",
    description: "Albemarle County · US-29 North corridor AOI · 2019–2023",
  },
  rwatershed: {
    label:       "Rivanna Watershed",
    s3Key:       "merged_smap_gedi-rwatershed.json",
    description: "All 8 jurisdictions · Rivanna River watershed AOI · 2019–2023",
  },
  rviewpark: {
    label:       "Riverview Park",
    s3Key:       "merged_smap_gedi-rviewpark.json",
    description: "Charlottesville · Riverview Park AOI · 2021–2022",
  },
};

// ── Color palette (consistent with SplitPanelDashboard) ──────────────────────
const JURIS_COLORS: Record<string, string> = {
  Albemarle:       "#2d6a4f",
  Augusta:         "#40916c",
  Buckingham:      "#1a759f",
  Charlottesville: "#52b788",
  Fluvanna:        "#74c69d",
  Greene:          "#95d5b2",
  Louisa:          "#b7e4c7",
  Nelson:          "#d8f3dc",
  Orange:          "#1b4332",
  Rockingham:      "#168aad",
};

const LAG1_COLOR = "#f1a340";
const LAG2_COLOR = "#998ec3";

// ── Props ─────────────────────────────────────────────────────────────────────
interface AoiTimeSeriesPanelProps {
  initialDataset?: AoiDatasetKey;
}

// ─────────────────────────────────────────────────────────────────────────────
// Main component
// ─────────────────────────────────────────────────────────────────────────────
export default function AoiTimeSeriesPanel({
  initialDataset = "rwatershed",
}: AoiTimeSeriesPanelProps) {
  // ── State ──────────────────────────────────────────────────────────────────
  const [activeDataset,   setActiveDataset]   = useState<AoiDatasetKey>(initialDataset);
  const [aoiData,         setAoiData]         = useState<AoiRow[]>([]);
  const [loading,         setLoading]         = useState(true);
  const [error,           setError]           = useState<string | null>(null);
  const [selectedJuris,   setSelectedJuris]   = useState<string | null>(null);
  const [showLags,        setShowLags]        = useState(false);

  // ── Fetch data whenever the active dataset changes ─────────────────────────
  useEffect(() => {
    setLoading(true);
    setError(null);
    setSelectedJuris(null);

    const { s3Key } = AOI_DATASET_META[activeDataset];
    axios
      .get<AoiRow[]>(`${DATA_BASE_URL}/${s3Key}`)
      .then((res) => {
        setAoiData(res.data);
      })
      .catch((err) => {
        console.error("[AoiTimeSeriesPanel] fetch error:", err);
        setError(`Failed to load ${AOI_DATASET_META[activeDataset].label} data from S3.`);
      })
      .finally(() => setLoading(false));
  }, [activeDataset]);

  // ── Derive jurisdiction list from loaded data ──────────────────────────────
  const jurisdictions = Array.from(
    new Set(aoiData.map((r) => r.jurisdiction))
  ).sort();

  // ── Build chart rows: one per year, all jurisdictions as columns ───────────
  const years = Array.from(new Set(aoiData.map((r) => r.year))).sort();

  // Lookup: jurisdiction → year → AoiRow
  const byJurisYear: Record<string, Record<number, AoiRow>> = {};
  aoiData.forEach((r) => {
    if (!byJurisYear[r.jurisdiction]) byJurisYear[r.jurisdiction] = {};
    byJurisYear[r.jurisdiction][r.year] = r;
  });

  const displayJurisdictions = selectedJuris ? [selectedJuris] : jurisdictions;

  // Canopy height chart rows
  const heightRows = years.map((year) => {
    const row: Record<string, number | null | string> = { year };
    displayJurisdictions.forEach((j) => {
      const rec = byJurisYear[j]?.[year];
      row[`${j}_height`] = rec?.canopy_height_mean_m ?? null;
    });
    return row;
  });

  // Soil moisture chart rows (same-year + lags)
  const smRows = years.map((year) => {
    const row: Record<string, number | null | string> = { year };
    displayJurisdictions.forEach((j) => {
      const rec = byJurisYear[j]?.[year];
      row[`${j}_sm`]    = rec?.sm_mean_m3m3  ?? null;
      row[`${j}_smMin`] = rec?.sm_min        ?? null;
      row[`${j}_smMax`] = rec?.sm_max        ?? null;
      if (showLags && selectedJuris === j) {
        row[`${j}_lag1`] = rec?.sm_mean_lag1 ?? null;
        row[`${j}_lag2`] = rec?.sm_mean_lag2 ?? null;
      }
    });
    return row;
  });

  // ── Tooltip formatters ─────────────────────────────────────────────────────
  const heightFormatter = useCallback((v: unknown) => {
    if (typeof v !== "number") return String(v ?? "—");
    return `${v.toFixed(2)} m`;
  }, []);

  const smFormatter = useCallback((v: unknown) => {
    if (typeof v !== "number") return String(v ?? "—");
    return `${v.toFixed(4)} m³/m³`;
  }, []);

  // ── Render: loading / error guards ────────────────────────────────────────
  if (loading) {
    return (
      <div style={styles.centered}>
        <p style={styles.loadingText}>
          Loading {AOI_DATASET_META[activeDataset].label}…
        </p>
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ ...styles.centered, color: "#c0392b" }}>
        <p style={styles.loadingText}>{error}</p>
      </div>
    );
  }

  // ── Main render ────────────────────────────────────────────────────────────
  const meta = AOI_DATASET_META[activeDataset];

  return (
    <div style={styles.wrapper}>
      {/* ── Panel header ── */}
      <div style={styles.header}>
        <div>
          <h2 style={styles.headerTitle}>AOI Time-Series Analysis</h2>
          <p style={styles.headerSub}>{meta.description}</p>
        </div>
      </div>

      {/* ── Controls bar ── */}
      <div style={styles.controls}>
        {/* Dataset selector */}
        <label style={styles.label}>
          Area of Interest&nbsp;
          <select
            value={activeDataset}
            onChange={(e) => setActiveDataset(e.target.value as AoiDatasetKey)}
            style={styles.select}
          >
            {(Object.keys(AOI_DATASET_META) as AoiDatasetKey[]).map((k) => (
              <option key={k} value={k}>
                {AOI_DATASET_META[k].label}
              </option>
            ))}
          </select>
        </label>

        {/* Jurisdiction filter */}
        {jurisdictions.length > 1 && (
          <label style={styles.label}>
            Jurisdiction&nbsp;
            <select
              value={selectedJuris ?? ""}
              onChange={(e) =>
                setSelectedJuris(e.target.value === "" ? null : e.target.value)
              }
              style={styles.select}
            >
              <option value="">All jurisdictions</option>
              {jurisdictions.map((j) => (
                <option key={j} value={j}>
                  {j}
                </option>
              ))}
            </select>
          </label>
        )}

        {/* Lag toggle — only meaningful when a single jurisdiction is shown */}
        {selectedJuris && (
          <label style={{ ...styles.label, cursor: "pointer" }}>
            <input
              type="checkbox"
              checked={showLags}
              onChange={(e) => setShowLags(e.target.checked)}
              style={{ marginRight: "0.3rem" }}
            />
            Show soil moisture lags
          </label>
        )}

        {/* Clear jurisdiction selection */}
        {selectedJuris && (
          <button
            onClick={() => { setSelectedJuris(null); setShowLags(false); }}
            style={styles.clearBtn}
          >
            ✕ Clear ({selectedJuris})
          </button>
        )}
      </div>

      {/* ── Charts ── */}
      <div style={styles.chartsWrapper}>
        {/* ── Chart 1: Canopy Height ── */}
        <section style={styles.chartSection}>
          <h3 style={styles.chartTitle}>
            GEDI Canopy Height (m)
            {selectedJuris ? ` — ${selectedJuris}` : " — All Jurisdictions"}
          </h3>
          <p style={styles.chartSource}>
            Source: GEDI Level 2A (GEDI02_A v002) · NASA Earthdata
          </p>
          <ResponsiveContainer width="100%" height={240}>
            <LineChart
              data={heightRows}
              margin={{ top: 8, right: 24, left: 0, bottom: 8 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#e8e8e8" />
              <XAxis
                dataKey="year"
                tick={{ fontSize: 11 }}
                label={{ value: "Year", position: "insideBottom", offset: -2, fontSize: 11 }}
              />
              <YAxis
                domain={["auto", "auto"]}
                tickFormatter={(v) => `${v}m`}
                tick={{ fontSize: 11 }}
                width={46}
                label={{
                  value: "Height (m)",
                  angle: -90,
                  position: "insideLeft",
                  offset: 10,
                  fontSize: 11,
                }}
              />
              <Tooltip formatter={heightFormatter} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Brush dataKey="year" height={18} stroke="#b7e4c7" />

              {displayJurisdictions.map((j) => (
                <Line
                  key={`${j}_height`}
                  type="monotone"
                  dataKey={`${j}_height`}
                  name={`${j}`}
                  stroke={JURIS_COLORS[j] ?? "#888"}
                  strokeWidth={2}
                  dot={{ r: 4 }}
                  activeDot={{ r: 6 }}
                  connectNulls
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </section>

        {/* ── Chart 2: Soil Moisture ── */}
        <section style={styles.chartSection}>
          <h3 style={styles.chartTitle}>
            SMAP Soil Moisture (m³/m³)
            {selectedJuris ? ` — ${selectedJuris}` : " — All Jurisdictions"}
          </h3>
          <p style={styles.chartSource}>
            Source: SMAP Enhanced L3 (SPL3SMP_E v006) · NASA Earthdata
          </p>
          <ResponsiveContainer width="100%" height={240}>
            <LineChart
              data={smRows}
              margin={{ top: 8, right: 24, left: 0, bottom: 8 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#e8e8e8" />
              <XAxis
                dataKey="year"
                tick={{ fontSize: 11 }}
                label={{ value: "Year", position: "insideBottom", offset: -2, fontSize: 11 }}
              />
              <YAxis
                domain={[0.15, 0.45]}
                tickFormatter={(v) => v.toFixed(2)}
                tick={{ fontSize: 11 }}
                width={46}
                label={{
                  value: "SM (m³/m³)",
                  angle: -90,
                  position: "insideLeft",
                  offset: 10,
                  fontSize: 11,
                }}
              />
              <Tooltip formatter={smFormatter} />
              <Legend wrapperStyle={{ fontSize: 11 }} />

              {/* 2019 SMAP data quality warning line */}
              <ReferenceLine
                x={2019}
                stroke="#e74c3c"
                strokeDasharray="4 2"
                label={{ value: "⚠ 32-day window", fontSize: 9, fill: "#e74c3c", position: "top" }}
              />

              {/* Same-year SM per jurisdiction */}
              {displayJurisdictions.map((j) => (
                <Line
                  key={`${j}_sm`}
                  type="monotone"
                  dataKey={`${j}_sm`}
                  name={`${j} SM`}
                  stroke={JURIS_COLORS[j] ?? "#888"}
                  strokeWidth={2}
                  dot={{ r: 3 }}
                  connectNulls
                />
              ))}

              {/* Lag-1 line — only when single jurisdiction + showLags */}
              {selectedJuris && showLags && (
                <Line
                  type="monotone"
                  dataKey={`${selectedJuris}_lag1`}
                  name={`${selectedJuris} SM lag-1`}
                  stroke={LAG1_COLOR}
                  strokeWidth={1.5}
                  strokeDasharray="5 3"
                  dot={false}
                  connectNulls
                />
              )}

              {/* Lag-2 line — only when single jurisdiction + showLags */}
              {selectedJuris && showLags && (
                <Line
                  type="monotone"
                  dataKey={`${selectedJuris}_lag2`}
                  name={`${selectedJuris} SM lag-2`}
                  stroke={LAG2_COLOR}
                  strokeWidth={1.5}
                  strokeDasharray="2 4"
                  dot={false}
                  connectNulls
                />
              )}
            </LineChart>
          </ResponsiveContainer>
        </section>

        {/* ── Coverage summary table ── */}
        <section style={styles.tableSection}>
          <h3 style={styles.chartTitle}>Data Coverage Summary</h3>
          <div style={styles.tableWrapper}>
            <table style={styles.table}>
              <thead>
                <tr>
                  <th style={styles.th}>Jurisdiction</th>
                  <th style={styles.th}>Years Available</th>
                  <th style={styles.th}>Canopy Height Range (m)</th>
                  <th style={styles.th}>SM Range (m³/m³)</th>
                  <th style={styles.th}>Observations</th>
                </tr>
              </thead>
              <tbody>
                {jurisdictions.map((j) => {
                  const rows = aoiData.filter((r) => r.jurisdiction === j);
                  const heights = rows
                    .map((r) => r.canopy_height_mean_m)
                    .filter((v): v is number => v != null);
                  const sms = rows
                    .map((r) => r.sm_mean_m3m3)
                    .filter((v): v is number => v != null);
                  const yearList = rows.map((r) => r.year).sort().join(", ");
                  const hMin = heights.length ? Math.min(...heights).toFixed(2) : "—";
                  const hMax = heights.length ? Math.max(...heights).toFixed(2) : "—";
                  const sMin = sms.length ? Math.min(...sms).toFixed(4) : "—";
                  const sMax = sms.length ? Math.max(...sms).toFixed(4) : "—";

                  return (
                    <tr
                      key={j}
                      style={{
                        ...styles.tr,
                        background: selectedJuris === j ? "#f0fdf4" : "transparent",
                        cursor: "pointer",
                      }}
                      onClick={() =>
                        setSelectedJuris((prev) => (prev === j ? null : j))
                      }
                    >
                      <td style={{ ...styles.td, fontWeight: 600, color: JURIS_COLORS[j] ?? "#333" }}>
                        {j}
                      </td>
                      <td style={styles.td}>{yearList}</td>
                      <td style={styles.td}>
                        {heights.length ? `${hMin} – ${hMax}` : "—"}
                      </td>
                      <td style={styles.td}>
                        {sms.length ? `${sMin} – ${sMax}` : "—"}
                      </td>
                      <td style={styles.td}>{rows.length}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p style={styles.tableNote}>
            Click a row to isolate that jurisdiction in the charts above.
          </p>
        </section>

        {/* ── Data quality notes ── */}
        <div style={styles.dataNote}>
          <strong>Data quality notes:</strong>
          <ul style={{ margin: "0.3rem 0 0 1.2rem", padding: 0 }}>
            <li>
              2019 SMAP value represents only 32 days (Jan–Feb). Treat with caution
              in trend analysis.
            </li>
            <li>
              Lag fields are <code>null</code> for the first 1–2 years of each
              jurisdiction&apos;s record (insufficient prior-year data).
            </li>
            {activeDataset === "rviewpark" && (
              <li>
                Riverview Park has only 2 observations (2021–2022, Charlottesville
                only). Trend analysis is not meaningful for this AOI.
              </li>
            )}
            {activeDataset === "route29north" && (
              <li>
                Route 29 North covers Albemarle County only. Cross-jurisdiction
                comparison is not applicable for this AOI.
              </li>
            )}
          </ul>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Inline styles
// ─────────────────────────────────────────────────────────────────────────────
const styles: Record<string, React.CSSProperties> = {
  wrapper: {
    display:        "flex",
    flexDirection:  "column",
    fontFamily:     "sans-serif",
    background:     "#f4f6f8",
    minHeight:      "100%",
  },
  centered: {
    display:        "flex",
    alignItems:     "center",
    justifyContent: "center",
    padding:        "2rem",
  },
  loadingText: {
    fontSize:  "0.9rem",
    color:     "#555",
  },
  header: {
    background: "#1a759f",
    color:      "#fff",
    padding:    "0.6rem 1.5rem",
    flexShrink: 0,
  },
  headerTitle: {
    margin:     0,
    fontSize:   "1rem",
    fontWeight: 700,
  },
  headerSub: {
    margin:   "0.15rem 0 0",
    fontSize: "0.75rem",
    opacity:  0.85,
  },
  controls: {
    display:       "flex",
    alignItems:    "center",
    flexWrap:      "wrap",
    gap:           "1.2rem",
    padding:       "0.5rem 1.5rem",
    background:    "#fff",
    borderBottom:  "1px solid #ddd",
    flexShrink:    0,
  },
  label: {
    fontSize:   "0.85rem",
    color:      "#333",
    display:    "flex",
    alignItems: "center",
    gap:        "0.3rem",
  },
  select: {
    fontSize:     "0.85rem",
    padding:      "0.2rem 0.4rem",
    border:       "1px solid #bbb",
    borderRadius: "4px",
    background:   "#fff",
    cursor:       "pointer",
  },
  clearBtn: {
    fontSize:     "0.8rem",
    padding:      "0.25rem 0.6rem",
    background:   "#1a759f",
    color:        "#fff",
    border:       "none",
    borderRadius: "4px",
    cursor:       "pointer",
  },
  chartsWrapper: {
    padding:   "1rem 1.5rem",
    overflowY: "auto",
  },
  chartSection: {
    background:   "#fff",
    borderRadius: "6px",
    padding:      "1rem 1.25rem",
    marginBottom: "1rem",
    border:       "1px solid #e0e0e0",
  },
  chartTitle: {
    margin:     "0 0 0.1rem",
    fontSize:   "0.9rem",
    fontWeight: 700,
    color:      "#1a759f",
  },
  chartSource: {
    margin:   "0 0 0.6rem",
    fontSize: "0.72rem",
    color:    "#888",
  },
  tableSection: {
    background:   "#fff",
    borderRadius: "6px",
    padding:      "1rem 1.25rem",
    marginBottom: "1rem",
    border:       "1px solid #e0e0e0",
  },
  tableWrapper: {
    overflowX: "auto",
  },
  table: {
    width:          "100%",
    borderCollapse: "collapse",
    fontSize:       "0.82rem",
  },
  th: {
    textAlign:    "left",
    padding:      "0.4rem 0.6rem",
    background:   "#f0fdf4",
    borderBottom: "2px solid #b7e4c7",
    fontWeight:   600,
    color:        "#1b4332",
    whiteSpace:   "nowrap",
  },
  td: {
    padding:      "0.35rem 0.6rem",
    borderBottom: "1px solid #eee",
    color:        "#333",
  },
  tr: {
    transition: "background 0.15s",
  },
  tableNote: {
    marginTop: "0.4rem",
    fontSize:  "0.72rem",
    color:     "#888",
  },
  dataNote: {
    background:   "#fffbeb",
    border:       "1px solid #fde68a",
    borderRadius: "6px",
    padding:      "0.75rem 1rem",
    fontSize:     "0.78rem",
    color:        "#78350f",
    lineHeight:   1.6,
    marginBottom: "1rem",
  },
};
