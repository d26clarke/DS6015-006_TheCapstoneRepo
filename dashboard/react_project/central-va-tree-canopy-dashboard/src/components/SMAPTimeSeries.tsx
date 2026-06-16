import Plotly from 'plotly.js-dist-min';
import _createPlotlyComponent from 'react-plotly.js/factory';

const createPlotlyComponent =
  (_createPlotlyComponent as { default?: any }).default ?? _createPlotlyComponent;
 
// Create the custom safe React wrapper
const Plot = createPlotlyComponent(Plotly as any);

import { useEffect, useState } from "react";

import axios from "axios";

import DATA_BASE_URL from "../config";

interface SMAPRecord {
  date: string;       // Matches "2015-01-01"
  year: number;       // Matches 2015 (Note: this is a number, not a string)
  county: string;     // Matches "Albemarle", "Augusta", etc.
  sm_mean_m3m3: number;
  valid_days: number;
  n_pixels: number;   // Matches 33
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

  //const years = [...new Set(data.map(d => d.year))].sort();
  // 2. Extracted years as numbers and sorted chronologically
  const years = [...new Set(data.map(d => d.year))].sort((a, b) => a - b);

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
          title: { text: "Annual Mean Soil Moisture — Study Area" },
          xaxis: { title: {text: "Year"} },
          yaxis: { title: {text: "Soil Moisture (m³/m³)"}, range: [0.1, 0.4] },
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
