import Plotly from 'plotly.js-dist-min';
import _createPlotlyComponent from 'react-plotly.js/factory';

const createPlotlyComponent =
  (_createPlotlyComponent as { default?: any }).default ?? _createPlotlyComponent;
 
// Create the custom safe React wrapper
const Plot = createPlotlyComponent(Plotly as any);

import { useEffect, useState } from "react";

import axios from "axios";
import DATA_BASE_URL from "../config";

//const Plot = createPlotlyComponent(Plotly as any);
//const Plot = createPlotlyComponent(Plotly);

//import axios from "axios";
//import DATA_BASE_URL from "../config";

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
          title: { text: "Tree Canopy Cover (%) — 2015 vs 2020" },
          xaxis: { title: {text: "Jurisdiction"} },
          yaxis: { title: {text: "Canopy Cover (%)"}, range: [0, 80] },
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