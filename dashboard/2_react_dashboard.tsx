// =============================================================================
// 2. React Dashboard Components
// =============================================================================
// Project structure:
//   src/
//     config.ts
//     App.tsx
//     components/
//       Header.tsx
//       SMAPTimeSeries.tsx
//       CanopyCoverBar.tsx
//       Footer.tsx
//
// Install dependencies:
//   npm create vite@latest cville-canopy-dashboard -- --template react-ts
//   cd cville-canopy-dashboard
//   npm install plotly.js react-plotly.js axios
//   npm install @types/plotly.js
// =============================================================================


// ─────────────────────────────────────────────────────────────────────────────
// FILE: src/config.ts
// ─────────────────────────────────────────────────────────────────────────────
/*
const DATA_BASE_URL =
  import.meta.env.PROD
    ? "https://YOUR_CLOUDFRONT_DOMAIN/dashboard-data"  // ← replace after Step 3
    : "/data";                                          // local dev fallback

export default DATA_BASE_URL;
*/


// ─────────────────────────────────────────────────────────────────────────────
// FILE: src/components/Header.tsx
// ─────────────────────────────────────────────────────────────────────────────
/*
import React from "react";
import DATA_BASE_URL from "../config";

export default function Header() {
  return (
    <header style={{
      background: "#1b4332", color: "#fff",
      padding: "1rem 2rem", display: "flex",
      alignItems: "center", justifyContent: "space-between"
    }}>
      <div>
        <h1 style={{ margin: 0, fontSize: "1.4rem" }}>
          Central Virginia Tree Canopy Change Detection
        </h1>
        <p style={{ margin: 0, fontSize: "0.85rem", opacity: 0.8 }}>
          City of Charlottesville + 6 Counties · 2015–2020 · USGS 3DEP LiDAR + SMAP
        </p>
      </div>
      <a
        href={`${DATA_BASE_URL}/methodology.html`}
        target="_blank"
        rel="noopener noreferrer"
        style={{
          color: "#d8f3dc", fontWeight: 600, fontSize: "0.9rem",
          textDecoration: "none", border: "1px solid #d8f3dc",
          padding: "0.4rem 0.9rem", borderRadius: "4px"
        }}
      >
        View Methodology Notebook →
      </a>
    </header>
  );
}
*/


// ─────────────────────────────────────────────────────────────────────────────
// FILE: src/components/SMAPTimeSeries.tsx
// ─────────────────────────────────────────────────────────────────────────────
/*
import React, { useEffect, useState } from "react";
import Plot from "react-plotly.js";
import axios from "axios";
import DATA_BASE_URL from "../config";

interface SMAPRecord {
  year: string;
  lat: number;
  lon: number;
  sm_mean_m3m3: number;
  valid_days: number;
}

export default function SMAPTimeSeries() {
  const [data, setData] = useState<SMAPRecord[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    axios.get<SMAPRecord[]>(`${DATA_BASE_URL}/smap_annual_means.json`)
      .then(res => { setData(res.data); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  if (loading) return <p>Loading soil moisture data…</p>;

  const years = [...new Set(data.map(d => d.year))].sort();

  // Aggregate mean per year across all pixels
  const yearlyMeans = years.map(yr => {
    const subset = data.filter(d => d.year === yr);
    const mean = subset.reduce((s, d) => s + d.sm_mean_m3m3, 0) / subset.length;
    return { year: yr, mean: parseFloat(mean.toFixed(4)) };
  });

  const trace = {
    x: yearlyMeans.map(d => d.year),
    y: yearlyMeans.map(d => d.mean),
    type: "scatter" as const,
    mode: "lines+markers" as const,
    name: "Study Area Mean",
    line: { color: "#2d6a4f", width: 2 },
    marker: { size: 8 }
  };

  return (
    <section style={{ padding: "1.5rem 2rem" }}>
      <h2 style={{ color: "#1b4332" }}>Soil Moisture Trend (SMAP SPL3SMP_E)</h2>
      <Plot
        data={[trace]}
        layout={{
          title: "Annual Mean Soil Moisture — Study Area",
          xaxis: { title: "Year" },
          yaxis: { title: "Soil Moisture (m³/m³)", range: [0.1, 0.4] },
          width: 860, height: 400,
          margin: { t: 50, l: 60, r: 20, b: 50 }
        }}
        config={{ responsive: true }}
      />
      <p style={{ fontSize: "0.8rem", color: "#555" }}>
        Source: NASA SMAP SPL3SMP_E v006 · AM overpass · 9 km resolution ·
        Bbox: Charlottesville + Albemarle + Buckingham + Fluvanna + Greene + Nelson + Orange + Louisa
      </p>
    </section>
  );
}
*/


// ─────────────────────────────────────────────────────────────────────────────
// FILE: src/components/CanopyCoverBar.tsx
// ─────────────────────────────────────────────────────────────────────────────
/*
import React, { useEffect, useState } from "react";
import Plot from "react-plotly.js";
import axios from "axios";
import DATA_BASE_URL from "../config";

interface CanopyRecord {
  jurisdiction: string;
  canopy_2015_pct: number;
  canopy_2020_pct: number;
  change_pct: number;
}

export default function CanopyCoverBar() {
  const [data, setData] = useState<CanopyRecord[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    axios.get<CanopyRecord[]>(`${DATA_BASE_URL}/canopy_summary.json`)
      .then(res => { setData(res.data); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  if (loading) return <p>Loading canopy data…</p>;

  const jurisdictions = data.map(d => d.jurisdiction);

  const trace2015 = {
    x: jurisdictions,
    y: data.map(d => d.canopy_2015_pct),
    name: "2015 Canopy %",
    type: "bar" as const,
    marker: { color: "#52b788" }
  };

  const trace2020 = {
    x: jurisdictions,
    y: data.map(d => d.canopy_2020_pct),
    name: "2020 Canopy %",
    type: "bar" as const,
    marker: { color: "#1b4332" }
  };

  return (
    <section style={{ padding: "1.5rem 2rem" }}>
      <h2 style={{ color: "#1b4332" }}>Tree Canopy Cover by Jurisdiction</h2>
      <Plot
        data={[trace2015, trace2020]}
        layout={{
          barmode: "group",
          title: "Tree Canopy Cover (%) — 2015 vs 2020",
          xaxis: { title: "Jurisdiction" },
          yaxis: { title: "Canopy Cover (%)", range: [0, 80] },
          width: 860, height: 420,
          margin: { t: 50, l: 60, r: 20, b: 80 },
          legend: { orientation: "h", y: -0.25 }
        }}
        config={{ responsive: true }}
      />
      <p style={{ fontSize: "0.8rem", color: "#555" }}>
        Source: USGS 3DEP LiDAR — VA_ChesapeakeBaySouth_2015 (baseline) &
        VA_NShenandoah_1_2020 (current) · CHM derived from ground-normalised point clouds
      </p>
    </section>
  );
}
*/


// ─────────────────────────────────────────────────────────────────────────────
// FILE: src/components/Footer.tsx
// ─────────────────────────────────────────────────────────────────────────────
/*
import React, { useEffect, useState } from "react";
import axios from "axios";
import DATA_BASE_URL from "../config";

interface Metadata {
  project_title: string;
  last_updated: string;
}

export default function Footer() {
  const [meta, setMeta] = useState<Metadata | null>(null);

  useEffect(() => {
    axios.get<Metadata>(`${DATA_BASE_URL}/metadata.json`)
      .then(res => setMeta(res.data));
  }, []);

  return (
    <footer style={{
      background: "#f1f8f4", borderTop: "1px solid #b7e4c7",
      padding: "1rem 2rem", fontSize: "0.8rem", color: "#555",
      display: "flex", justifyContent: "space-between"
    }}>
      <span>
        University of Virginia · DS Capstone ·{" "}
        {meta ? meta.project_title : "Central Virginia Tree Canopy Change Detection"}
      </span>
      <span>Last updated: {meta ? meta.last_updated : "—"}</span>
    </footer>
  );
}
*/


// ─────────────────────────────────────────────────────────────────────────────
// FILE: src/App.tsx
// ─────────────────────────────────────────────────────────────────────────────
/*
import React from "react";
import Header from "./components/Header";
import SMAPTimeSeries from "./components/SMAPTimeSeries";
import CanopyCoverBar from "./components/CanopyCoverBar";
import Footer from "./components/Footer";

export default function App() {
  return (
    <div style={{ fontFamily: "Inter, sans-serif", minHeight: "100vh",
                  display: "flex", flexDirection: "column" }}>
      <Header />
      <main style={{ flex: 1, background: "#fff" }}>
        <CanopyCoverBar />
        <hr style={{ border: "none", borderTop: "1px solid #e9ecef", margin: "0 2rem" }} />
        <SMAPTimeSeries />
      </main>
      <Footer />
    </div>
  );
}
*/
