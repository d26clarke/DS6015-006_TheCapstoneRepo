// ─────────────────────────────────────────────────────────────────────────────
//
// PolicyPanel.tsx
//
// Multi-domain policy context panel for the Central Virginia Tree Canopy
// Dashboard.  Loads the pre-built policy_panel_dataset.json from S3 and
// renders four coordinated views:
//
//   1. Canopy + SOL Pass Rate   — dual-axis line chart (GEDI × Education)
//   2. Crime Rate Trend         — Group A crimes per 100k line chart
//   3. Socioeconomic Context    — median income + % bachelor's line charts
//   4. Community Health Profile — CDC PLACES bar charts (static 2023)
//
// Jurisdiction selector and compare toggle drive all four charts.
//
// Props:
//   none — self-contained, loads data independently
//
// Data contract:
//   PolicyRow — see interface below
//   File:  policy_panel_dataset.json  (one record per jurisdiction × year)
//
// Dependencies (already in package.json):
//   recharts, axios
//
// ─────────────────────────────────────────────────────────────────────────────

import React, { useEffect, useState, useMemo } from "react";
import axios from "axios";
import {
  ComposedChart,
  LineChart,
  BarChart,
  Bar,
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

// ── Types ─────────────────────────────────────────────────────────────────────

export interface PolicyRow {
  jurisdiction:                       string;
  year:                               number;
  // GEDI
  canopy_height_mean_m:               number | null;
  mean_canopy_cover:                  number | null;
  total_valid_shots:                  number | null;
  // Education
  sol_pass_rate_all:                  number | null;
  // Crime (Tier 1)
  offense_total:                      number | null;
  group_a_crimes_per_100k:            number | null;
  total_arrests:                      number | null;
  arrests_per_100k:                   number | null;
  // Crime (Tier 2)
  aggravated_assault_reported:        number | null;
  drug_narcotic_violations_reported:  number | null;
  weapon_law_violations_reported:     number | null;
  // ACS
  median_household_income:            number | null;
  total_population:                   number | null;
  pct_bachelors_plus:                 number | null;
  // CDC PLACES
  health_obesity_pct:                 number | null;
  health_diabetes_pct:                number | null;
  health_depression_pct:              number | null;
  health_mhlth_pct:                   number | null;
  health_bphigh_pct:                  number | null;
  health_csmoking_pct:                number | null;
  // Flags
  flag_low_gedi_shots:                boolean;
  flag_sol_missing:                   boolean;
}

// ── Constants ─────────────────────────────────────────────────────────────────

const DATA_KEY = "policy_panel_dataset.json";

const JURISDICTIONS = [
  "Albemarle",
  "Augusta",
  "Buckingham",
  "Charlottesville",
  "Fluvanna",
  "Greene",
  "Louisa",
  "Nelson",
  "Rockingham",
];

const JURIS_COLORS: Record<string, string> = {
  Albemarle:       "#2563eb",
  Augusta:         "#16a34a",
  Buckingham:      "#9333ea",
  Charlottesville: "#dc2626",
  Fluvanna:        "#d97706",
  Greene:          "#0891b2",
  Louisa:          "#db2777",
  Nelson:          "#65a30d",
  Rockingham:      "#7c3aed",
};

const HEALTH_METRICS: { key: keyof PolicyRow; label: string; color: string }[] = [
  { key: "health_obesity_pct",    label: "Obesity",             color: "#ef4444" },
  { key: "health_diabetes_pct",   label: "Diabetes",            color: "#f97316" },
  { key: "health_depression_pct", label: "Depression",          color: "#8b5cf6" },
  { key: "health_mhlth_pct",      label: "Poor Mental Health",  color: "#6366f1" },
  { key: "health_bphigh_pct",     label: "High Blood Pressure", color: "#ec4899" },
  { key: "health_csmoking_pct",   label: "Smoking",             color: "#78716c" },
];

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Safe toFixed — returns "—" when value is null/undefined/NaN */
const safeFmt = (v: unknown, decimals = 1): string =>
  typeof v === "number" && isFinite(v) ? v.toFixed(decimals) : "—";

/** Recharts-safe formatter: accepts ValueType (number | string | undefined) */
const tooltipFmt =
  (suffix = "", prefix = "", decimals = 1) =>
  (v: unknown): [string, string] =>
    [`${prefix}${safeFmt(v, decimals)}${suffix}`, ""];

const fmtK = (v: number | null | undefined): string =>
  typeof v === "number" ? `$${(v / 1000).toFixed(0)}k` : "—";

// ── Sub-components ────────────────────────────────────────────────────────────

const SectionHeader: React.FC<{ title: string; subtitle: string }> = ({
  title,
  subtitle,
}) => (
  <div className="mb-2">
    <h3 className="text-sm font-semibold text-gray-800">{title}</h3>
    <p className="text-xs text-gray-500">{subtitle}</p>
  </div>
);

// ── Main Component ────────────────────────────────────────────────────────────

const PolicyPanel: React.FC = () => {
  const [allData, setAllData]             = useState<PolicyRow[]>([]);
  const [loading, setLoading]             = useState(true);
  const [error, setError]                 = useState<string | null>(null);
  const [selectedJuris, setSelectedJuris] = useState<string>("Albemarle");
  const [compareJuris, setCompareJuris]   = useState<string>("Augusta");
  const [enableCompare, setEnableCompare] = useState(false);
  const [activeTab, setActiveTab]         = useState<"canopy" | "crime" | "socio" | "health">("canopy");

  // ── Fetch ──────────────────────────────────────────────────────────────────
  useEffect(() => {
    setLoading(true);
    setError(null);
    axios
      .get<PolicyRow[]>(`${DATA_BASE_URL}/${DATA_KEY}`)
      .then((res) => {
        const raw = res.data;
        setAllData(Array.isArray(raw) ? raw : []);
      })
      .catch((err: Error) => {
        setError(`Failed to load policy panel data: ${err.message}`);
      })
      .finally(() => setLoading(false));
  }, []);

  // ── Derived data ───────────────────────────────────────────────────────────

  const primarySeries = useMemo(
    () =>
      allData
        .filter((r) => r.jurisdiction === selectedJuris)
        .sort((a, b) => a.year - b.year),
    [allData, selectedJuris]
  );

  const compareSeries = useMemo(
    () =>
      enableCompare
        ? allData
            .filter((r) => r.jurisdiction === compareJuris)
            .sort((a, b) => a.year - b.year)
        : [],
    [allData, compareJuris, enableCompare]
  );

  // Merge primary + compare into a single array keyed by year for recharts
  const mergedTimeSeries = useMemo(() => {
    const byYear: Record<number, Record<string, number | null | undefined>> = {};

    for (const r of primarySeries) {
      byYear[r.year] = {
        year:                          r.year,
        [`${selectedJuris}_canopy`]:   r.canopy_height_mean_m,
        [`${selectedJuris}_cover`]:    r.mean_canopy_cover != null ? r.mean_canopy_cover * 100 : null,
        [`${selectedJuris}_sol`]:      r.sol_pass_rate_all,
        [`${selectedJuris}_crime`]:    r.group_a_crimes_per_100k,
        [`${selectedJuris}_income`]:   r.median_household_income,
        [`${selectedJuris}_edu`]:      r.pct_bachelors_plus,
      };
    }

    if (enableCompare) {
      for (const r of compareSeries) {
        if (!byYear[r.year]) byYear[r.year] = { year: r.year };
        byYear[r.year][`${compareJuris}_canopy`] = r.canopy_height_mean_m;
        byYear[r.year][`${compareJuris}_cover`]  = r.mean_canopy_cover != null ? r.mean_canopy_cover * 100 : null;
        byYear[r.year][`${compareJuris}_sol`]    = r.sol_pass_rate_all;
        byYear[r.year][`${compareJuris}_crime`]  = r.group_a_crimes_per_100k;
        byYear[r.year][`${compareJuris}_income`] = r.median_household_income;
        byYear[r.year][`${compareJuris}_edu`]    = r.pct_bachelors_plus;
      }
    }

    return Object.values(byYear).sort(
      (a, b) => (a.year as number) - (b.year as number)
    );
  }, [primarySeries, compareSeries, selectedJuris, compareJuris, enableCompare]);

  // Health snapshot — most recent non-null CDC row per jurisdiction
  const healthSnapshot = useMemo(() => {
    return JURISDICTIONS.map((j) => {
      const rows = allData.filter(
        (r) => r.jurisdiction === j && r.health_obesity_pct != null
      );
      const latest = rows[rows.length - 1];
      if (!latest) return null;
      return {
        jurisdiction: j,
        obesity:    latest.health_obesity_pct,
        diabetes:   latest.health_diabetes_pct,
        depression: latest.health_depression_pct,
        mhlth:      latest.health_mhlth_pct,
        bphigh:     latest.health_bphigh_pct,
        smoking:    latest.health_csmoking_pct,
      };
    }).filter(Boolean) as {
      jurisdiction: string;
      obesity:    number | null;
      diabetes:   number | null;
      depression: number | null;
      mhlth:      number | null;
      bphigh:     number | null;
      smoking:    number | null;
    }[];
  }, [allData]);

  // Latest stats card for selected jurisdiction
  const latestRow = useMemo(
    () => [...primarySeries].reverse().find((r) => r.canopy_height_mean_m != null) ?? null,
    [primarySeries]
  );

  // Crime breakdown averages for selected jurisdiction
  const crimeBreakdown = useMemo(() => {
    const cats = [
      { key: "aggravated_assault_reported"       as keyof PolicyRow, label: "Aggravated Assault" },
      { key: "drug_narcotic_violations_reported"  as keyof PolicyRow, label: "Drug / Narcotic" },
      { key: "weapon_law_violations_reported"     as keyof PolicyRow, label: "Weapon Violations" },
    ];
    return cats.map(({ key, label }) => {
      const vals = allData
        .filter((r) => r.jurisdiction === selectedJuris && r[key] != null)
        .map((r) => r[key] as number);
      const avg = vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : 0;
      return { label, value: Math.round(avg) };
    });
  }, [allData, selectedJuris]);

  // ── Colors ─────────────────────────────────────────────────────────────────
  const primaryColor = JURIS_COLORS[selectedJuris] ?? "#2563eb";
  const compareColor = JURIS_COLORS[compareJuris]  ?? "#16a34a";

  const tabs = [
    { id: "canopy" as const, label: "Canopy & Education" },
    { id: "crime"  as const, label: "Crime Trends" },
    { id: "socio"  as const, label: "Socioeconomic" },
    { id: "health" as const, label: "Community Health" },
  ];

  // ── Loading / Error ────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-500 text-sm">
        Loading policy panel data…
      </div>
    );
  }
  if (error) {
    return (
      <div className="flex items-center justify-center h-64 text-red-600 text-sm">
        {error}
      </div>
    );
  }

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="bg-white rounded-lg border border-gray-200 shadow-sm p-4 space-y-4">

      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-bold text-gray-900">Policy Context Panel</h2>
          <p className="text-xs text-gray-500 mt-0.5">
            Education · Crime · Socioeconomic · Health — 9 jurisdictions, 2019–2025
          </p>
        </div>

        {/* Controls */}
        <div className="flex flex-wrap items-center gap-3 text-xs">
          <div className="flex items-center gap-1.5">
            <span className="text-gray-600 font-medium">Jurisdiction:</span>
            <select
              className="border border-gray-300 rounded px-2 py-1 text-xs bg-white"
              value={selectedJuris}
              onChange={(e) => setSelectedJuris(e.target.value)}
            >
              {JURISDICTIONS.map((j) => (
                <option key={j} value={j}>{j}</option>
              ))}
            </select>
          </div>

          <label className="flex items-center gap-1.5 cursor-pointer">
            <input
              type="checkbox"
              checked={enableCompare}
              onChange={(e) => setEnableCompare(e.target.checked)}
              className="rounded"
            />
            <span className="text-gray-600">Compare:</span>
          </label>

          {enableCompare && (
            <select
              className="border border-gray-300 rounded px-2 py-1 text-xs bg-white"
              value={compareJuris}
              onChange={(e) => setCompareJuris(e.target.value)}
            >
              {JURISDICTIONS.filter((j) => j !== selectedJuris).map((j) => (
                <option key={j} value={j}>{j}</option>
              ))}
            </select>
          )}
        </div>
      </div>

      {/* KPI strip */}
      {latestRow && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          {[
            {
              label: "Canopy Height",
              value: `${safeFmt(latestRow.canopy_height_mean_m)} m`,
              note: String(latestRow.year),
            },
            {
              label: "Canopy Cover",
              value: latestRow.mean_canopy_cover != null
                ? `${(latestRow.mean_canopy_cover * 100).toFixed(1)}%`
                : "—",
              note: String(latestRow.year),
            },
            {
              label: "SOL Pass Rate",
              value: latestRow.sol_pass_rate_all != null
                ? `${safeFmt(latestRow.sol_pass_rate_all)}%`
                : "—",
              note: String(latestRow.year),
            },
            {
              label: "Median Income",
              value: fmtK(latestRow.median_household_income),
              note: String(latestRow.year),
            },
          ].map(({ label, value, note }) => (
            <div key={label} className="bg-gray-50 rounded p-2 border border-gray-100">
              <div className="text-xs text-gray-500">{label}</div>
              <div className="text-lg font-bold text-gray-900 leading-tight">{value}</div>
              <div className="text-xs text-gray-400">{note}</div>
            </div>
          ))}
        </div>
      )}

      {/* Tab bar */}
      <div className="flex gap-1 border-b border-gray-200">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setActiveTab(t.id)}
            className={`px-3 py-1.5 text-xs font-medium rounded-t transition-colors ${
              activeTab === t.id
                ? "bg-white border border-b-white border-gray-200 text-blue-700 -mb-px"
                : "text-gray-500 hover:text-gray-700"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* ── Tab: Canopy & Education ── */}
      {activeTab === "canopy" && (
        <div className="space-y-4">
          <SectionHeader
            title="Canopy Height vs. SOL Pass Rate"
            subtitle="GEDI mean canopy height (m) and K-12 SOL pass rate (%) over time. SOL data unavailable for 2020 (COVID disruption)."
          />
          <ResponsiveContainer width="100%" height={280}>
            <ComposedChart data={mergedTimeSeries} margin={{ top: 8, right: 24, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="year" tick={{ fontSize: 11 }} />
              <YAxis
                yAxisId="canopy"
                orientation="left"
                tick={{ fontSize: 11 }}
                label={{ value: "Height (m)", angle: -90, position: "insideLeft", offset: 10, style: { fontSize: 10 } }}
              />
              <YAxis
                yAxisId="sol"
                orientation="right"
                domain={[40, 100]}
                tick={{ fontSize: 11 }}
                label={{ value: "SOL Pass %", angle: 90, position: "insideRight", offset: 10, style: { fontSize: 10 } }}
              />
              <Tooltip
                formatter={(value, name) => [
                  typeof value === "number" ? value.toFixed(1) : String(value ?? "—"),
                  String(name),
                ]}
              />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <ReferenceLine
                yAxisId="sol"
                y={70}
                stroke="#fbbf24"
                strokeDasharray="4 4"
                label={{ value: "70% target", fontSize: 9 }}
              />
              <Line yAxisId="canopy" type="monotone" dataKey={`${selectedJuris}_canopy`} name={`${selectedJuris} Canopy (m)`} stroke={primaryColor} strokeWidth={2} dot={{ r: 3 }} connectNulls />
              <Line yAxisId="sol"    type="monotone" dataKey={`${selectedJuris}_sol`}    name={`${selectedJuris} SOL %`}      stroke={primaryColor} strokeWidth={2} strokeDasharray="5 3" dot={{ r: 3 }} connectNulls />
              {enableCompare && (
                <>
                  <Line yAxisId="canopy" type="monotone" dataKey={`${compareJuris}_canopy`} name={`${compareJuris} Canopy (m)`} stroke={compareColor} strokeWidth={2} dot={{ r: 3 }} connectNulls />
                  <Line yAxisId="sol"    type="monotone" dataKey={`${compareJuris}_sol`}    name={`${compareJuris} SOL %`}      stroke={compareColor} strokeWidth={2} strokeDasharray="5 3" dot={{ r: 3 }} connectNulls />
                </>
              )}
            </ComposedChart>
          </ResponsiveContainer>

          <SectionHeader
            title="Mean Canopy Cover (%)"
            subtitle="Fraction of GEDI footprints with canopy cover, expressed as a percentage."
          />
          <ResponsiveContainer width="100%" height={180}>
            <LineChart data={mergedTimeSeries} margin={{ top: 4, right: 24, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="year" tick={{ fontSize: 11 }} />
              <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} tickFormatter={(v) => `${v}%`} />
              <Tooltip formatter={tooltipFmt("%")} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Line type="monotone" dataKey={`${selectedJuris}_cover`} name={`${selectedJuris} Cover %`} stroke={primaryColor} strokeWidth={2} dot={{ r: 3 }} connectNulls />
              {enableCompare && (
                <Line type="monotone" dataKey={`${compareJuris}_cover`} name={`${compareJuris} Cover %`} stroke={compareColor} strokeWidth={2} dot={{ r: 3 }} connectNulls />
              )}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* ── Tab: Crime Trends ── */}
      {activeTab === "crime" && (
        <div className="space-y-4">
          <SectionHeader
            title="Group A Crimes per 100,000 Population"
            subtitle="NIBRS Group A offense rate (2019–2021 only — PDFs available for those years). Null values shown as gaps."
          />
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={mergedTimeSeries} margin={{ top: 8, right: 24, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="year" tick={{ fontSize: 11 }} />
              <YAxis
                tick={{ fontSize: 11 }}
                label={{ value: "Crimes / 100k", angle: -90, position: "insideLeft", offset: 10, style: { fontSize: 10 } }}
              />
              <Tooltip formatter={tooltipFmt("", "", 1)} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Line type="monotone" dataKey={`${selectedJuris}_crime`} name={`${selectedJuris}`} stroke={primaryColor} strokeWidth={2} dot={{ r: 4 }} connectNulls={false} />
              {enableCompare && (
                <Line type="monotone" dataKey={`${compareJuris}_crime`} name={`${compareJuris}`} stroke={compareColor} strokeWidth={2} dot={{ r: 4 }} connectNulls={false} />
              )}
            </LineChart>
          </ResponsiveContainer>

          <SectionHeader
            title="Offense Breakdown (2019–2021 average)"
            subtitle="Average annual reported offenses for key crime categories for the selected jurisdiction."
          />
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={crimeBreakdown} margin={{ top: 4, right: 16, bottom: 4, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="label" tick={{ fontSize: 10 }} />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip />
              <Bar dataKey="value" name="Avg. Annual Offenses" fill={primaryColor} radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* ── Tab: Socioeconomic ── */}
      {activeTab === "socio" && (
        <div className="space-y-4">
          <SectionHeader
            title="Median Household Income"
            subtitle="ACS 5-Year estimates (2019–2024). Values in thousands of dollars."
          />
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={mergedTimeSeries} margin={{ top: 8, right: 24, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="year" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`} />
              <Tooltip
                formatter={(v) => [
                  typeof v === "number" ? `$${(v / 1000).toFixed(1)}k` : "—",
                  "Median Income",
                ]}
              />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Line type="monotone" dataKey={`${selectedJuris}_income`} name={`${selectedJuris}`} stroke={primaryColor} strokeWidth={2} dot={{ r: 3 }} connectNulls />
              {enableCompare && (
                <Line type="monotone" dataKey={`${compareJuris}_income`} name={`${compareJuris}`} stroke={compareColor} strokeWidth={2} dot={{ r: 3 }} connectNulls />
              )}
            </LineChart>
          </ResponsiveContainer>

          <SectionHeader
            title="Educational Attainment — % Bachelor's Degree or Higher"
            subtitle="ACS 5-Year estimates (2019–2024)."
          />
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={mergedTimeSeries} margin={{ top: 4, right: 24, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="year" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => `${v}%`} />
              <Tooltip formatter={tooltipFmt("%")} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Line type="monotone" dataKey={`${selectedJuris}_edu`} name={`${selectedJuris}`} stroke={primaryColor} strokeWidth={2} dot={{ r: 3 }} connectNulls />
              {enableCompare && (
                <Line type="monotone" dataKey={`${compareJuris}_edu`} name={`${compareJuris}`} stroke={compareColor} strokeWidth={2} dot={{ r: 3 }} connectNulls />
              )}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* ── Tab: Community Health ── */}
      {activeTab === "health" && (
        <div className="space-y-4">
          <SectionHeader
            title="CDC PLACES Health Indicators — All Jurisdictions (2023)"
            subtitle="Age-adjusted prevalence (%). Lower is generally better. Source: CDC PLACES dataset swc5-untb."
          />
          {HEALTH_METRICS.map(({ key, label, color }) => (
            <div key={String(key)}>
              <p className="text-xs font-medium text-gray-700 mb-1">{label} (%)</p>
              <ResponsiveContainer width="100%" height={100}>
                <BarChart
                  data={healthSnapshot.map((h) => ({
                    jurisdiction: h.jurisdiction.substring(0, 5),
                    value: h[key as keyof typeof h],
                  }))}
                  margin={{ top: 0, right: 8, bottom: 0, left: -20 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" vertical={false} />
                  <XAxis dataKey="jurisdiction" tick={{ fontSize: 9 }} />
                  <YAxis tick={{ fontSize: 9 }} tickFormatter={(v) => `${v}%`} />
                  <Tooltip
                    formatter={(v) => [
                      typeof v === "number" ? `${v.toFixed(1)}%` : "—",
                      label,
                    ]}
                  />
                  <Bar dataKey="value" name={label} fill={color} radius={[2, 2, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          ))}
        </div>
      )}

      {/* Data coverage note */}
      <div className="text-xs text-gray-400 border-t border-gray-100 pt-2">
        <span className="font-medium">Data coverage:</span>{" "}
        GEDI 2019–2025 · SOL 2019–2025 (2020 missing) · Crime 2019–2021 (NIBRS PDFs) ·
        ACS 2019–2024 · CDC PLACES 2023 (age-adjusted). Crime data for 2022–2025 not yet available.
      </div>
    </div>
  );
};

export default PolicyPanel;
