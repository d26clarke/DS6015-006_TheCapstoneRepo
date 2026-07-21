// ─── SplitPanelDashboard.tsx ─────────────────────────────────────────────────
//
// Split-panel dashboard:
//   LEFT  — React-Leaflet choropleth map of Virginia jurisdictions.
//           Dropdowns control the active metric (height, cover, or soil
//           moisture/lags) and year. Clicking a polygon isolates that
//           jurisdiction across every chart on the right panel.
//   RIGHT — Recharts line graphs: Canopy Height, Canopy Cover, and Soil
//           Moisture (+ lags), all driven by the same jurisdiction selection.
//
// This version merges what were previously two parallel, independently
// selectable datasets (GEDI02A height vs. GEDI02B cover) into one component
// with a SINGLE selection state and a SINGLE unified metric type. The two
// were duplicated in the prior version (two jurisdiction-selection states,
// two metric key/meta systems) which is what caused: a broken Canopy Height
// chart (meters treated as a 0-1 fraction and multiplied by 100), dead
// lag-line blocks, and a real React duplicate-key warning when nothing was
// selected. See the previous review for full detail.
//
// Data sources (fetched from S3 via the DATA_BASE_URL config):
//   • merged_smap_gedi.json     — GEDI Level 2A canopy HEIGHT, per jurisdiction
//   • merged_smap_gedi02B.json  — GEDI Level 2B canopy COVER, per jurisdiction
//   • smap_timeseries.json      — regional SMAP aggregate (2015–2023)
//   • Per-jurisdiction GeoJSON  — boundary polygons (one file per jurisdiction)
//
// Dependencies to add to package.json:
//   npm install leaflet react-leaflet @types/leaflet recharts axios
//   npm install -D @types/geojson
//
// CSS: import "leaflet/dist/leaflet.css" in App.tsx

import React, { useEffect, useState, useCallback, useMemo, useRef } from "react";
import {
  MapContainer,
  TileLayer,
  GeoJSON,
  useMap,
} from "react-leaflet";
import L, { Layer, type LeafletMouseEvent, type PathOptions } from "leaflet";
import type { Feature, FeatureCollection, Geometry } from "geojson";
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
} from "recharts";

import DATA_BASE_URL from "../config";

import {
  type SmapRow,
  type MergedGedi02ARow,
  type MergedGedi02BRow,
  type CombinedRow,
  type MetricKey,
  METRIC_META,
  AVAILABLE_YEARS,
  type AvailableYear,
} from "../types";
import { valueToColor, computeDomain } from "../colorScale";
import { LagLegend } from "./LagLegend";

// ── GeoJSON file map ─────────────────────────────────────────────────────────
// Corrected to match the jurisdictions actually present in the merged
// datasets (previously included Buckingham/Orange, and was MISSING Augusta
// and Rockingham entirely -- meaning those two counties, despite having
// real data in both merged_smap_gedi.json and merged_smap_gedi02B.json,
// never rendered on the map or in the default "all jurisdictions" chart view).
//
// TODO: Augusta_aoi.geojson and Rockingham_aoi.geojson need to be uploaded
// to S3 under geo-json-files/ -- they did not exist in the original map.
// Buckingham is kept: it has GEDI02A (height) data even though it currently
// has no GEDI02B (cover) data -- selecting Cover for Buckingham will
// correctly show "No data" via the existing null-handling below, rather
// than silently omitting a jurisdiction that does have *some* real data.
// Augusta:         "geo-json-files/Augusta_aoi.geojson",       // TODO: upload to S3
//  Rockingham:      "geo-json-files/Rockingham_aoi.geojson",    // TODO: upload to S3
const GEOJSON_KEYS: Record<string, string> = {
  Albemarle:       "geo-json-files/Albemarle_aoi.geojson",
  Buckingham:      "geo-json-files/Buckingham_aoi.geojson",
  Charlottesville: "geo-json-files/Charlottesville_aoi.geojson",
  Fluvanna:        "geo-json-files/Fluvanna_aoi.geojson",
  Greene:          "geo-json-files/Greene_aoi.geojson",
  Louisa:          "geo-json-files/Louisa_aoi.geojson",
  Nelson:          "geo-json-files/Nelson_aoi.geojson",
};

// ── Jurisdiction list (display order) ────────────────────────────────────────
const JURISDICTIONS = Object.keys(GEOJSON_KEYS);

// ── Recharts line colors ──────────────────────────────────────────────────────
const JURIS_COLORS: Record<string, string> = {
  Albemarle:       "#2d6a4f",
  Augusta:         "#40916c",
  Buckingham:      "#588157",
  Charlottesville: "#52b788",
  Fluvanna:        "#74c69d",
  Greene:          "#95d5b2",
  Louisa:          "#b7e4c7",
  Nelson:          "#d8f3dc",
  Rockingham:      "#1b4332",
};

// ── Color constants ───────────────────────────────────────────────────────────
const HIGHLIGHT_COLOR = "#ff7800";
const DEFAULT_WEIGHT  = 1.5;
const HIGHLIGHT_WEIGHT = 3;

/** Merge GEDI02A (height) and GEDI02B (cover) rows on (jurisdiction, year)
 *  into one combined record. Soil moisture fields exist identically in both
 *  source files -- 02B is treated as canonical (matches the map's original
 *  choropleth behavior) but 02A's copy is used as a fallback for any
 *  (jurisdiction, year) combination that 02B doesn't have a row for. */
function buildCombinedRows(
  gedi02A: MergedGedi02ARow[],
  gedi02B: MergedGedi02BRow[]
): CombinedRow[] {
  const key = (j: string, y: number) => `${j}__${y}`;
  const map = new Map<string, CombinedRow>();

  const getOrInit = (jurisdiction: string, year: number): CombinedRow => {
    const k = key(jurisdiction, year);
    let row = map.get(k);
    if (!row) {
      row = {
        jurisdiction, year,
        canopy_height_mean_m: null,
        mean_canopy_cover: null,
        sm_mean_m3m3: null,
        sm_mean_lag1: null,
        sm_mean_lag2: null,
      };
      map.set(k, row);
    }
    return row;
  };

  gedi02A.forEach((r) => {
    const row = getOrInit(r.jurisdiction, r.year);
    row.canopy_height_mean_m = r.canopy_height_mean_m;
    row.sm_mean_m3m3 ??= r.sm_mean_m3m3;
    row.sm_mean_lag1 ??= r.sm_mean_lag1;
    row.sm_mean_lag2 ??= r.sm_mean_lag2;
  });

  gedi02B.forEach((r) => {
    const row = getOrInit(r.jurisdiction, r.year);
    row.mean_canopy_cover = r.mean_canopy_cover;
    row.sm_mean_m3m3 = r.sm_mean_m3m3; // 02B is canonical; overrides 02A if both present
    row.sm_mean_lag1 = r.sm_mean_lag1;
    row.sm_mean_lag2 = r.sm_mean_lag2;
  });

  return Array.from(map.values());
}

// ─────────────────────────────────────────────────────────────────────────────
// Sub-component: resets map view to Virginia bounding box on mount
// ─────────────────────────────────────────────────────────────────────────────
function VirginiaBounds() {
  const map = useMap();
  useEffect(() => {
    map.fitBounds([
      [37.5, -80.0],
      [38.6, -77.8],
    ]);
  }, [map]);
  return null;
}

// ─────────────────────────────────────────────────────────────────────────────
// Main component
// ─────────────────────────────────────────────────────────────────────────────
export default function SplitPanelDashboard() {
  // ── Data state ──────────────────────────────────────────────────────────────
  const [mergedGedi02AData, setMergedGedi02AData] = useState<MergedGedi02ARow[]>([]);
  const [mergedGedi02BData, setMergedGedi02BData] = useState<MergedGedi02BRow[]>([]);
  const [smapData,   setSmapData]   = useState<SmapRow[]>([]);
  const [geoJsonMap, setGeoJsonMap] = useState<Record<string, FeatureCollection>>({});
  const [loading,    setLoading]    = useState(true);
  const [error,      setError]      = useState<string | null>(null);

  // ── UI state ────────────────────────────────────────────────────────────────
  // Single metric and single jurisdiction selection now (previously two of
  // each, one per dataset) -- both height and cover charts, plus the
  // choropleth, all respond to the same selection.
  const [selectedMetric, setSelectedMetric] = useState<MetricKey>("mean_canopy_cover");
  const [selectedYear,   setSelectedYear]   = useState<AvailableYear>(2022);
  const [selectedJuris,  setSelectedJuris]  = useState<string | null>(null);

  const highlightedLayerRef = useRef<L.Path | null>(null);

  // ── Fetch all data on mount ──────────────────────────────────────────────────
  useEffect(() => {
    const fetchAll = async () => {
      try {
        const [merged02ARes, merged02BRes, smapRes] = await Promise.all([
          axios.get<MergedGedi02ARow[]>(`${DATA_BASE_URL}/merged_smap_gedi.json`),
          axios.get<MergedGedi02BRow[]>(`${DATA_BASE_URL}/merged_smap_gedi02B.json`),
          axios.get<SmapRow[]>(`${DATA_BASE_URL}/smap_timeseries.json`),
        ]);
        setMergedGedi02AData(merged02ARes.data);
        setMergedGedi02BData(merged02BRes.data);
        setSmapData(smapRes.data);

        const geoResults = await Promise.allSettled(
          JURISDICTIONS.map((name) =>
            axios
              .get<FeatureCollection>(`${DATA_BASE_URL}/${GEOJSON_KEYS[name]}`)
              .then((r) => ({ name, data: r.data }))
          )
        );

        const geoMap: Record<string, FeatureCollection> = {};
        geoResults.forEach((result) => {
          if (result.status === "fulfilled") {
            geoMap[result.value.name] = result.value.data;
          }
        });
        setGeoJsonMap(geoMap);
      } catch (err) {
        setError("Failed to load dashboard data from S3.");
        console.error(err);
      } finally {
        setLoading(false);
      }
    };
    fetchAll();
  }, []);

  // ── Combined rows (single merge of 02A + 02B, built once per data load) ──────
  const combinedRows = useMemo(
    () => buildCombinedRows(mergedGedi02AData, mergedGedi02BData),
    [mergedGedi02AData, mergedGedi02BData]
  );

  // Year-filtered rows for the choropleth
  const activeRows = useMemo(
    () => combinedRows.filter((r) => r.year === selectedYear),
    [combinedRows, selectedYear]
  );
  const [domainMin, domainMax] = computeDomain(activeRows, selectedMetric);

  // jurisdiction -> value lookup for the currently selected metric + year
  const valueByJuris: Record<string, number | null> = {};
  activeRows.forEach((r) => {
    valueByJuris[r.jurisdiction] = r[selectedMetric];
  });

  // ── GeoJSON style function ────────────────────────────────────────────────────
  const styleFeature = useCallback(
    (jurisName: string, isSelected: boolean): PathOptions => {
      const value = valueByJuris[jurisName] ?? null;
      const fillColor = valueToColor(value, domainMin, domainMax, selectedMetric);
      return {
        fillColor,
        fillOpacity: 0.75,
        color: isSelected ? HIGHLIGHT_COLOR : "#444",
        weight: isSelected ? HIGHLIGHT_WEIGHT : DEFAULT_WEIGHT,
        opacity: 1,
      };
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [valueByJuris, domainMin, domainMax, selectedMetric, selectedJuris]
  );

  // ── Tooltip value formatting, generic across all 5 metrics ──────────────────
  function formatMetricValue(value: number | null, metric: MetricKey): string {
    if (value == null) return "No data";
    const meta = METRIC_META[metric];
    const displayNumber = metric === "mean_canopy_cover" ? value * 100 : value;
    return `${displayNumber.toFixed(meta.decimals)}${metric === "mean_canopy_cover" ? "" : " "}${meta.unit}`;
  }

  // ── Event handlers for each GeoJSON layer ────────────────────────────────────
  const onEachFeature = useCallback(
    (jurisName: string) =>
      (_feature: Feature<Geometry>, layer: Layer) => {
        const path = layer as L.Path;
        const meta = METRIC_META[selectedMetric];
        const value = valueByJuris[jurisName];

        path.bindTooltip(
          `<strong>${jurisName}</strong><br/>${meta.label}: ${formatMetricValue(value ?? null, selectedMetric)}`,
          { sticky: true, direction: "top" }
        );

        path.on("click", (_e: LeafletMouseEvent) => {
          if (highlightedLayerRef.current && highlightedLayerRef.current !== path) {
            highlightedLayerRef.current.setStyle(styleFeature(jurisName, false));
          }
          if (selectedJuris === jurisName) {
            setSelectedJuris(null);
            path.setStyle(styleFeature(jurisName, false));
            highlightedLayerRef.current = null;
          } else {
            setSelectedJuris(jurisName);
            path.setStyle({ color: HIGHLIGHT_COLOR, weight: HIGHLIGHT_WEIGHT, fillOpacity: 0.9 });
            highlightedLayerRef.current = path;
          }
        });

        path.on("mouseover", () => {
          if (selectedJuris !== jurisName) {
            path.setStyle({ weight: HIGHLIGHT_WEIGHT, fillOpacity: 0.9 });
          }
        });
        path.on("mouseout", () => {
          if (selectedJuris !== jurisName) {
            path.setStyle(styleFeature(jurisName, false));
          }
        });
      },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [valueByJuris, selectedMetric, selectedJuris, styleFeature]
  );

  // ── Chart jurisdictions: single source now, not two parallel arrays ─────────
  const chartJurisdictions = selectedJuris ? [selectedJuris] : JURISDICTIONS;

  // Year-keyed lookup: jurisdiction -> year -> CombinedRow
  const combinedByJurisYear: Record<string, Record<number, CombinedRow>> = {};
  combinedRows.forEach((r) => {
    if (!combinedByJurisYear[r.jurisdiction]) combinedByJurisYear[r.jurisdiction] = {};
    combinedByJurisYear[r.jurisdiction][r.year] = r;
  });

  // ── Build time-series chart data ─────────────────────────────────────────────
  const allYears = smapData.map((r) => r.year).sort((a, b) => a - b);
  const smapByYear: Record<number, SmapRow> = {};
  smapData.forEach((r) => { smapByYear[r.year] = r; });

  const chartRows = allYears.map((year) => {
    const row: Record<string, number | null | string> = { year };
    const smap = smapByYear[year];
    if (smap) {
      row["sm_regional"] = smap.sm_mean;
    }
    chartJurisdictions.forEach((j) => {
      const combined = combinedByJurisYear[j]?.[year];
      if (combined) {
        row[`${j}_height`] = combined.canopy_height_mean_m;
        row[`${j}_cover`]  = combined.mean_canopy_cover != null
          ? parseFloat((combined.mean_canopy_cover * 100).toFixed(2))
          : null;
        row[`${j}_sm`]     = combined.sm_mean_m3m3;
        row[`${j}_lag1`]   = combined.sm_mean_lag1;
        row[`${j}_lag2`]   = combined.sm_mean_lag2;
      }
    });
    return row;
  });

  // ── Render ───────────────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div style={styles.centered}>
        <p style={{ fontFamily: "sans-serif", color: "#555" }}>Loading dashboard data from S3…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ ...styles.centered, color: "red", fontFamily: "sans-serif" }}>{error}</div>
    );
  }

  return (
    <div style={styles.wrapper}>
      {/* ── Header ── */}
      <header style={styles.header}>
        <h1 style={styles.headerTitle}>Central Virginia Tree Canopy &amp; Soil Moisture Dashboard</h1>
        <p style={styles.headerSub}>
          SMAP Enhanced (SPL3SMP_E v006) · GEDI Level 2A (GEDI02_A v002) · GEDI Level 2B (GEDI02_B v002) · 2019–2023
        </p>
      </header>

      {/* ── Controls bar ── */}
      <div style={styles.controls}>
        <label style={styles.label}>
          Metric&nbsp;
          <select
            value={selectedMetric}
            onChange={(e) => setSelectedMetric(e.target.value as MetricKey)}
            style={styles.select}
          >
            {(Object.keys(METRIC_META) as MetricKey[]).map((k) => (
              <option key={k} value={k}>{METRIC_META[k].label}</option>
            ))}
          </select>
        </label>

        <label style={styles.label}>
          Year&nbsp;
          <select
            value={selectedYear}
            onChange={(e) => setSelectedYear(Number(e.target.value) as AvailableYear)}
            style={styles.select}
          >
            {AVAILABLE_YEARS.map((y) => (
              <option key={y} value={y}>{y}</option>
            ))}
          </select>
        </label>

        {selectedJuris && (
          <button onClick={() => setSelectedJuris(null)} style={styles.clearBtn}>
            ✕ Clear selection ({selectedJuris})
          </button>
        )}
      </div>

      {/* ── Split panel ── */}
      <div style={styles.splitPanel}>
        {/* LEFT: Leaflet choropleth map */}
        <div style={styles.mapPanel}>
          <MapContainer style={{ width: "100%", height: "100%" }} center={[38.05, -78.9]} zoom={9} scrollWheelZoom>
            <VirginiaBounds />
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              opacity={0.4}
            />
            {JURISDICTIONS.map((jurisName) => {
              const geoData = geoJsonMap[jurisName];
              if (!geoData) return null;
              return (
                <GeoJSON
                  key={`${jurisName}-${selectedMetric}-${selectedYear}`}
                  data={geoData}
                  style={() => styleFeature(jurisName, selectedJuris === jurisName)}
                  onEachFeature={onEachFeature(jurisName)}
                />
              );
            })}
            <div style={{ position: "relative" }}>
              <LagLegend metric={selectedMetric} min={domainMin} max={domainMax} />
            </div>
          </MapContainer>
        </div>

        {/* RIGHT: Recharts time-series panel */}
        <div style={styles.chartPanel}>
          <h2 style={styles.chartTitle}>
            {selectedJuris ? `${selectedJuris} — Multi-Year Timeline` : "All Jurisdictions — Regional Overview"}
          </h2>

          {/* ── Canopy Height chart (meters -- NOT a percentage) ── */}
          <p style={styles.chartSubtitle}>GEDI Canopy Height (m) · 2019–2023</p>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={chartRows} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e0e0e0" />
              <XAxis dataKey="year" tick={{ fontSize: 11 }} />
              <YAxis domain={[0, 30]} tickFormatter={(v) => `${v}m`} tick={{ fontSize: 11 }} width={42} />
              <Tooltip formatter={(v) => (typeof v === "number" ? `${v.toFixed(1)} m` : String(v ?? ""))} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <ReferenceLine x={2019} stroke="#aaa" strokeDasharray="4 2" label={{ value: "GEDI start", fontSize: 10, fill: "#888" }} />
              {chartJurisdictions.map((j) => (
                <Line
                  key={`${j}_height`}
                  type="monotone"
                  dataKey={`${j}_height`}
                  name={`${j} height`}
                  stroke={JURIS_COLORS[j] ?? "#888"}
                  strokeWidth={2}
                  dot={{ r: 3 }}
                  connectNulls
                />
              ))}
            </LineChart>
          </ResponsiveContainer>

          {/* ── Canopy Cover chart ── */}
          <p style={styles.chartSubtitle}>GEDI Canopy Cover (%) · 2019–2023</p>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={chartRows} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e0e0e0" />
              <XAxis dataKey="year" tick={{ fontSize: 11 }} />
              <YAxis domain={[0, 100]} tickFormatter={(v) => `${v}%`} tick={{ fontSize: 11 }} width={42} />
              <Tooltip formatter={(v) => (typeof v === "number" ? `${v.toFixed(1)}%` : String(v ?? ""))} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <ReferenceLine x={2019} stroke="#aaa" strokeDasharray="4 2" label={{ value: "GEDI start", fontSize: 10, fill: "#888" }} />
              {chartJurisdictions.map((j) => (
                <Line
                  key={`${j}_cover`}
                  type="monotone"
                  dataKey={`${j}_cover`}
                  name={`${j} cover`}
                  stroke={JURIS_COLORS[j] ?? "#888"}
                  strokeWidth={2}
                  dot={{ r: 3 }}
                  connectNulls
                />
              ))}
            </LineChart>
          </ResponsiveContainer>

          {/* ── Soil Moisture chart (same-year + lags) ── */}
          <p style={styles.chartSubtitle}>SMAP Soil Moisture (m³/m³) · Regional 2015–2023 + Jurisdiction Lags</p>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={chartRows} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e0e0e0" />
              <XAxis dataKey="year" tick={{ fontSize: 11 }} />
              <YAxis domain={[0.15, 0.45]} tickFormatter={(v) => v.toFixed(2)} tick={{ fontSize: 11 }} width={42} />
              <Tooltip formatter={(v) => (typeof v === "number" ? v.toFixed(4) : String(v ?? ""))} />
              <Legend wrapperStyle={{ fontSize: 11 }} />

              <Line
                type="monotone" dataKey="sm_regional" name="Regional SM (mean)"
                stroke="#2171b5" strokeWidth={2.5} dot={{ r: 3 }} connectNulls
              />

              {/* Single .map() now (was previously duplicated across two
                  parallel jurisdiction arrays that were often identical,
                  causing a React duplicate-key warning) */}
              {chartJurisdictions.map((j) => (
                <Line
                  key={`${j}_sm`} type="monotone" dataKey={`${j}_sm`} name={`${j} SM`}
                  stroke={JURIS_COLORS[j] ?? "#888"} strokeWidth={1.5}
                  strokeDasharray="5 3" dot={false} connectNulls
                />
              ))}

              {/* Lag lines only shown when a single jurisdiction is selected
                  (previously duplicated into two near-identical blocks that
                  both referenced the same variable regardless of which
                  condition gated them) */}
              {selectedJuris && (
                <Line
                  type="monotone" dataKey={`${selectedJuris}_lag1`} name={`${selectedJuris} SM lag-1`}
                  stroke="#f1a340" strokeWidth={1.5} strokeDasharray="3 3" dot={false} connectNulls
                />
              )}
              {selectedJuris && (
                <Line
                  type="monotone" dataKey={`${selectedJuris}_lag2`} name={`${selectedJuris} SM lag-2`}
                  stroke="#998ec3" strokeWidth={1.5} strokeDasharray="2 4" dot={false} connectNulls
                />
              )}
            </LineChart>
          </ResponsiveContainer>

          <p style={styles.dataNote}>
            ⚠ 2019 SMAP value represents only 32 days (Jan–Feb). Lag fields are{" "}
            <code>null</code> for the first 1–2 years of each jurisdiction's record.
            Charlottesville has no 2020 or 2023 GEDI observations. Buckingham has no
            GEDI Level 2B (cover) data currently — its Cover chart line and choropleth
            fill (when Cover is the selected metric) will correctly show as empty/"No data".
          </p>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Inline styles (avoids external CSS dependency for portability)
// ─────────────────────────────────────────────────────────────────────────────
const styles: Record<string, React.CSSProperties> = {
  wrapper: { display: "flex", flexDirection: "column", height: "100vh", fontFamily: "sans-serif", background: "#f4f6f8" },
  centered: { display: "flex", alignItems: "center", justifyContent: "center", height: "100vh" },
  header: { background: "#1b4332", color: "#fff", padding: "0.6rem 1.5rem", flexShrink: 0 },
  headerTitle: { margin: 0, fontSize: "1.1rem", fontWeight: 700 },
  headerSub: { margin: "0.15rem 0 0", fontSize: "0.75rem", opacity: 0.8 },
  controls: { display: "flex", alignItems: "center", gap: "1.5rem", padding: "0.5rem 1.5rem", background: "#fff", borderBottom: "1px solid #ddd", flexShrink: 0 },
  label: { fontSize: "0.85rem", color: "#333", display: "flex", alignItems: "center", gap: "0.3rem" },
  select: { fontSize: "0.85rem", padding: "0.2rem 0.4rem", border: "1px solid #bbb", borderRadius: "4px", background: "#fff", cursor: "pointer" },
  clearBtn: { fontSize: "0.8rem", padding: "0.25rem 0.6rem", background: "#ff7800", color: "#fff", border: "none", borderRadius: "4px", cursor: "pointer" },
  splitPanel: { display: "flex", flex: 1, overflow: "hidden" },
  mapPanel: { flex: "0 0 50%", position: "relative", borderRight: "2px solid #ddd" },
  chartPanel: { flex: "0 0 50%", overflowY: "auto", padding: "1rem 1.25rem", background: "#fff" },
  chartTitle: { margin: "0 0 0.25rem", fontSize: "0.95rem", color: "#1b4332", fontWeight: 700 },
  chartSubtitle: { margin: "0.75rem 0 0.25rem", fontSize: "0.8rem", color: "#555", fontWeight: 600 },
  dataNote: { marginTop: "0.75rem", fontSize: "0.72rem", color: "#888", lineHeight: 1.5, borderTop: "1px solid #eee", paddingTop: "0.5rem" },
};
