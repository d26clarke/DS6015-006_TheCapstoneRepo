// ─── SplitPanelDashboard.tsx ─────────────────────────────────────────────────
//
// Split-panel dashboard:
//   LEFT  — React-Leaflet choropleth map of Virginia jurisdictions.
//           Dropdowns control the active metric and year.
//           Clicking a polygon isolates that jurisdiction on the right panel.
//   RIGHT — Recharts multi-axis line graph showing the full temporal history
//           for the selected jurisdiction (or all jurisdictions if none selected).
//
// Data sources (fetched from S3 via the DATA_BASE_URL config):
//   • merged_smap_gedi02B.json  — spatiotemporal, per-jurisdiction
//   • smap_timeseries.json      — regional SMAP aggregate (2015–2023)
//   • Per-jurisdiction GeoJSON  — boundary polygons (one file per jurisdiction)
//
// Dependencies to add to package.json:
//   npm install leaflet react-leaflet @types/leaflet recharts axios
//   npm install -D @types/geojson
//
// CSS: import "leaflet/dist/leaflet.css" in App.tsx

import React, { useEffect, useState, useCallback, useRef } from "react";
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
  type MergedRow,
  type MetricKey,
  METRIC_META,
  AVAILABLE_YEARS,
  type AvailableYear,
} from "../types";
import { valueToColor, computeDomain } from "../colorScale";
import { LagLegend } from "./LagLegend";

// ── GeoJSON file map ─────────────────────────────────────────────────────────
// Map each jurisdiction name (as it appears in merged_smap_gedi02B.json)
// to the S3 key of its boundary GeoJSON file.
// Add the remaining 7 jurisdiction files once they are available in S3.
const GEOJSON_KEYS: Record<string, string> = {
  Charlottesville: "geo-json-files/Charlottesville_aoi.geojson",
  Albemarle:       "geo-json-files/Albemarle_aoi.geojson",
  Buckingham:      "geo-json-files/Buckingham_aoi.geojson",
  Fluvanna:        "geo-json-files/Fluvanna_aoi.geojson",
  Greene:          "geo-json-files/Greene_aoi.geojson",
  Louisa:          "geo-json-files/Louisa_aoi.geojson",
  Nelson:          "geo-json-files/Nelson_aoi.geojson",
  Orange:          "geo-json-files/Orange_aoi.geojson",
};

// ── Jurisdiction list (display order) ────────────────────────────────────────
const JURISDICTIONS = Object.keys(GEOJSON_KEYS);

// ── Color constants ───────────────────────────────────────────────────────────
const HIGHLIGHT_COLOR = "#ff7800";
const DEFAULT_WEIGHT  = 1.5;
const HIGHLIGHT_WEIGHT = 3;

// ─────────────────────────────────────────────────────────────────────────────
// Sub-component: resets map view to Virginia bounding box on mount
// ─────────────────────────────────────────────────────────────────────────────
function VirginiaBounds() {
  const map = useMap();
  useEffect(() => {
    // Approximate bounding box covering all 8 study jurisdictions
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
  const [mergedData,  setMergedData]  = useState<MergedRow[]>([]);
  const [smapData,    setSmapData]    = useState<SmapRow[]>([]);
  const [geoJsonMap,  setGeoJsonMap]  = useState<Record<string, FeatureCollection>>({});
  const [loading,     setLoading]     = useState(true);
  const [error,       setError]       = useState<string | null>(null);

  // ── UI state ────────────────────────────────────────────────────────────────
  const [selectedMetric, setSelectedMetric] = useState<MetricKey>("mean_canopy_cover");
  const [selectedYear,   setSelectedYear]   = useState<AvailableYear>(2022);
  const [selectedJuris,  setSelectedJuris]  = useState<string | null>(null);

  // Ref to track highlighted layer for reset on re-click
  const highlightedLayerRef = useRef<L.Path | null>(null);

  // ── Fetch all data on mount ──────────────────────────────────────────────────
  useEffect(() => {
    const fetchAll = async () => {
      try {
        const [mergedRes, smapRes] = await Promise.all([
          axios.get<MergedRow[]>(`${DATA_BASE_URL}/merged_smap_gedi02B.json`),
          axios.get<SmapRow[]>(`${DATA_BASE_URL}/smap_timeseries.json`),
        ]);
        setMergedData(mergedRes.data);
        setSmapData(smapRes.data);

        // Fetch all GeoJSON boundary files in parallel
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

  // ── Derive choropleth domain for the active metric + year ───────────────────
  const activeRows = mergedData.filter((r) => r.year === selectedYear);
  const [domainMin, domainMax] = computeDomain(activeRows, selectedMetric);

  // ── Build a lookup: jurisdiction → metric value for the selected year ────────
  const valueByJuris: Record<string, number | null> = {};
  activeRows.forEach((r) => {
    valueByJuris[r.jurisdiction] = r[selectedMetric] as number | null;
  });

  // ── GeoJSON style function (memoized) ────────────────────────────────────────
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

  // ── Event handlers for each GeoJSON layer ────────────────────────────────────
  const onEachFeature = useCallback(
    (jurisName: string) =>
      (_feature: Feature<Geometry>, layer: Layer) => {
        const path = layer as L.Path;

        // Tooltip showing jurisdiction name + metric value
        const value = valueByJuris[jurisName];
        const meta  = METRIC_META[selectedMetric];
        const displayValue =
          value == null
            ? "No data"
            : selectedMetric === "mean_canopy_cover"
            ? `${(value * 100).toFixed(meta.decimals)}${meta.unit}`
            : `${value.toFixed(meta.decimals)} ${meta.unit}`;

        path.bindTooltip(
          `<strong>${jurisName}</strong><br/>${meta.label}: ${displayValue}`,
          { sticky: true, direction: "top" }
        );

        path.on("click", (_e: LeafletMouseEvent) => {
          // Reset previously highlighted layer
          if (
            highlightedLayerRef.current &&
            highlightedLayerRef.current !== path
          ) {
            highlightedLayerRef.current.setStyle(
              styleFeature(jurisName, false)
            );
          }
          // Toggle selection
          if (selectedJuris === jurisName) {
            setSelectedJuris(null);
            path.setStyle(styleFeature(jurisName, false));
            highlightedLayerRef.current = null;
          } else {
            setSelectedJuris(jurisName);
            path.setStyle({
              color: HIGHLIGHT_COLOR,
              weight: HIGHLIGHT_WEIGHT,
              fillOpacity: 0.9,
            });
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

  // ── Build time-series chart data ─────────────────────────────────────────────
  // Merge SMAP regional data (2015–2023) with per-jurisdiction GEDI data
  // (2019–2023). For the right panel we always show all years on the x-axis.
  const chartJurisdictions = selectedJuris ? [selectedJuris] : JURISDICTIONS;

  // Build a year-keyed lookup for GEDI data per jurisdiction
  const gediByJurisYear: Record<string, Record<number, MergedRow>> = {};
  mergedData.forEach((r) => {
    if (!gediByJurisYear[r.jurisdiction]) gediByJurisYear[r.jurisdiction] = {};
    gediByJurisYear[r.jurisdiction][r.year] = r;
  });

  // Build chart rows: one per year (2015–2023), SMAP always present,
  // GEDI only for 2019–2023
  const allYears = smapData.map((r) => r.year).sort();
  const smapByYear: Record<number, SmapRow> = {};
  smapData.forEach((r) => { smapByYear[r.year] = r; });

  const chartRows = allYears.map((year) => {
    const row: Record<string, number | null | string> = { year };
    // SMAP regional
    const smap = smapByYear[year];
    if (smap) {
      row["sm_regional"]     = smap.sm_mean;
      row["sm_regional_min"] = smap.sm_min;
      row["sm_regional_max"] = smap.sm_max;
    }
    // GEDI per jurisdiction
    chartJurisdictions.forEach((j) => {
      const gedi = gediByJurisYear[j]?.[year];
      if (gedi) {
        row[`${j}_canopy`]   = parseFloat((gedi.mean_canopy_cover * 100).toFixed(2));
        row[`${j}_sm`]       = gedi.sm_mean_m3m3;
        row[`${j}_lag1`]     = gedi.sm_mean_lag1;
        row[`${j}_lag2`]     = gedi.sm_mean_lag2;
      }
    });
    return row;
  });

  // ── Recharts line colors ──────────────────────────────────────────────────────
  const JURIS_COLORS: Record<string, string> = {
    Albemarle:      "#2d6a4f",
    Augusta:        "#40916c",
    Charlottesville:"#52b788",
    Fluvanna:       "#74c69d",
    Greene:         "#95d5b2",
    Louisa:         "#b7e4c7",
    Nelson:         "#d8f3dc",
    Rockingham:     "#1b4332",
  };

  // ── Render ───────────────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div style={styles.centered}>
        <p style={{ fontFamily: "sans-serif", color: "#555" }}>
          Loading dashboard data from S3…
        </p>
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ ...styles.centered, color: "red", fontFamily: "sans-serif" }}>
        {error}
      </div>
    );
  }

  return (
    <div style={styles.wrapper}>
      {/* ── Header ── */}
      <header style={styles.header}>
        <h1 style={styles.headerTitle}>
          Central Virginia Tree Canopy &amp; Soil Moisture Dashboard
        </h1>
        <p style={styles.headerSub}>
          SMAP Enhanced (SPL3SMP_E v006) · GEDI Level 2B (GEDI02_B v002) · 2019–2023
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
              <option key={k} value={k}>
                {METRIC_META[k].label}
              </option>
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
              <option key={y} value={y}>
                {y}
              </option>
            ))}
          </select>
        </label>

        {selectedJuris && (
          <button
            onClick={() => setSelectedJuris(null)}
            style={styles.clearBtn}
          >
            ✕ Clear selection ({selectedJuris})
          </button>
        )}
      </div>

      {/* ── Split panel ── */}
      <div style={styles.splitPanel}>
        {/* LEFT: Leaflet choropleth map */}
        <div style={styles.mapPanel}>
          <MapContainer
            style={{ width: "100%", height: "100%" }}
            center={[38.05, -78.9]}
            zoom={9}
            scrollWheelZoom
          >
            <VirginiaBounds />
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              opacity={0.4}
            />

            {/* Render one GeoJSON layer per jurisdiction */}
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

            {/* Color scale legend — positioned inside map container */}
            <div style={{ position: "relative" }}>
              <LagLegend
                metric={selectedMetric}
                min={domainMin}
                max={domainMax}
              />
            </div>
          </MapContainer>
        </div>

        {/* RIGHT: Recharts time-series panel */}
        <div style={styles.chartPanel}>
          <h2 style={styles.chartTitle}>
            {selectedJuris
              ? `${selectedJuris} — Multi-Year Timeline`
              : "All Jurisdictions — Regional Overview"}
          </h2>

          {/* ── Canopy Cover chart ── */}
          <p style={styles.chartSubtitle}>
            GEDI Canopy Cover (%) · 2019–2023
          </p>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={chartRows} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e0e0e0" />
              <XAxis dataKey="year" tick={{ fontSize: 11 }} />
              <YAxis
                domain={[0, 100]}
                tickFormatter={(v) => `${v}%`}
                tick={{ fontSize: 11 }}
                width={42}
              />
              {/* Broken Code causes a Recharts type signature mismatch
              <Tooltip formatter={(v: number) => `${v.toFixed(1)}%`} />
              */}
              <Tooltip
                formatter={(v) => {
                  if (typeof v !== "number") return String(v ?? "");
                  return `${v.toFixed(1)}%`;
                }}
              />
              <Legend wrapperStyle={{ fontSize: 11 }} />

              {/* GEDI overlap window reference lines */}
              <ReferenceLine x={2019} stroke="#aaa" strokeDasharray="4 2" label={{ value: "GEDI start", fontSize: 10, fill: "#888" }} />
              {chartJurisdictions.map((j) => (
                <Line
                  key={`${j}_canopy`}
                  type="monotone"
                  dataKey={`${j}_canopy`}
                  name={`${j} canopy`}
                  stroke={JURIS_COLORS[j] ?? "#888"}
                  strokeWidth={2}
                  dot={{ r: 3 }}
                  connectNulls
                />
              ))}
            </LineChart>
          </ResponsiveContainer>

          {/* ── Soil Moisture chart (same-year + lags) ── */}
          <p style={styles.chartSubtitle}>
            SMAP Soil Moisture (m³/m³) · Regional 2015–2023 + Jurisdiction Lags
          </p>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={chartRows} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e0e0e0" />
              <XAxis dataKey="year" tick={{ fontSize: 11 }} />
              <YAxis
                domain={[0.15, 0.45]}
                tickFormatter={(v) => v.toFixed(2)}
                tick={{ fontSize: 11 }}
                width={42}
              />
              {/* Broken Code causes a Recharts type signature mismatch 
              <Tooltip formatter={(v: number) => v.toFixed(4)} />
              
              */}
              <Tooltip
                formatter={(v) => {
                  if (typeof v !== "number") return String(v ?? "");
                  return `${v.toFixed(4)}%`;
                }}
              />

              <Legend wrapperStyle={{ fontSize: 11 }} />

              {/* Regional SMAP baseline */}
              <Line
                type="monotone"
                dataKey="sm_regional"
                name="Regional SM (mean)"
                stroke="#2171b5"
                strokeWidth={2.5}
                dot={{ r: 3 }}
                connectNulls
              />

              {/* Per-jurisdiction same-year SM */}
              {chartJurisdictions.map((j) => (
                <Line
                  key={`${j}_sm`}
                  type="monotone"
                  dataKey={`${j}_sm`}
                  name={`${j} SM`}
                  stroke={JURIS_COLORS[j] ?? "#888"}
                  strokeWidth={1.5}
                  strokeDasharray="5 3"
                  dot={false}
                  connectNulls
                />
              ))}

              {/* Lag-1 lines — only shown when a single jurisdiction is selected */}
              {selectedJuris && (
                <Line
                  type="monotone"
                  dataKey={`${selectedJuris}_lag1`}
                  name={`${selectedJuris} SM lag-1`}
                  stroke="#f1a340"
                  strokeWidth={1.5}
                  strokeDasharray="3 3"
                  dot={false}
                  connectNulls
                />
              )}

              {/* Lag-2 lines — only shown when a single jurisdiction is selected */}
              {selectedJuris && (
                <Line
                  type="monotone"
                  dataKey={`${selectedJuris}_lag2`}
                  name={`${selectedJuris} SM lag-2`}
                  stroke="#998ec3"
                  strokeWidth={1.5}
                  strokeDasharray="2 4"
                  dot={false}
                  connectNulls
                />
              )}
            </LineChart>
          </ResponsiveContainer>

          {/* ── Data quality note ── */}
          <p style={styles.dataNote}>
            ⚠ 2019 SMAP value represents only 32 days (Jan–Feb). Lag fields are{" "}
            <code>null</code> for the first 1–2 years of each jurisdiction's record.
            Charlottesville has no 2020 or 2023 GEDI observations.
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
  wrapper: {
    display: "flex",
    flexDirection: "column",
    height: "100vh",
    fontFamily: "sans-serif",
    background: "#f4f6f8",
  },
  centered: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    height: "100vh",
  },
  header: {
    background: "#1b4332",
    color: "#fff",
    padding: "0.6rem 1.5rem",
    flexShrink: 0,
  },
  headerTitle: {
    margin: 0,
    fontSize: "1.1rem",
    fontWeight: 700,
  },
  headerSub: {
    margin: "0.15rem 0 0",
    fontSize: "0.75rem",
    opacity: 0.8,
  },
  controls: {
    display: "flex",
    alignItems: "center",
    gap: "1.5rem",
    padding: "0.5rem 1.5rem",
    background: "#fff",
    borderBottom: "1px solid #ddd",
    flexShrink: 0,
  },
  label: {
    fontSize: "0.85rem",
    color: "#333",
    display: "flex",
    alignItems: "center",
    gap: "0.3rem",
  },
  select: {
    fontSize: "0.85rem",
    padding: "0.2rem 0.4rem",
    border: "1px solid #bbb",
    borderRadius: "4px",
    background: "#fff",
    cursor: "pointer",
  },
  clearBtn: {
    fontSize: "0.8rem",
    padding: "0.25rem 0.6rem",
    background: "#ff7800",
    color: "#fff",
    border: "none",
    borderRadius: "4px",
    cursor: "pointer",
  },
  splitPanel: {
    display: "flex",
    flex: 1,
    overflow: "hidden",
  },
  mapPanel: {
    flex: "0 0 50%",
    position: "relative",
    borderRight: "2px solid #ddd",
  },
  chartPanel: {
    flex: "0 0 50%",
    overflowY: "auto",
    padding: "1rem 1.25rem",
    background: "#fff",
  },
  chartTitle: {
    margin: "0 0 0.25rem",
    fontSize: "0.95rem",
    color: "#1b4332",
    fontWeight: 700,
  },
  chartSubtitle: {
    margin: "0.75rem 0 0.25rem",
    fontSize: "0.8rem",
    color: "#555",
    fontWeight: 600,
  },
  dataNote: {
    marginTop: "0.75rem",
    fontSize: "0.72rem",
    color: "#888",
    lineHeight: 1.5,
    borderTop: "1px solid #eee",
    paddingTop: "0.5rem",
  },
};
