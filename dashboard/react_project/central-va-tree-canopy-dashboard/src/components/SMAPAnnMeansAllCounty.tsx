import Plotly from 'plotly.js-dist-min';
import _createPlotlyComponent from 'react-plotly.js/factory';

const createPlotlyComponent =
  (_createPlotlyComponent as { default?: any }).default ?? _createPlotlyComponent;
 
const Plot = createPlotlyComponent(Plotly as any);

import { useEffect, useState } from "react";
import axios from "axios";
import DATA_BASE_URL from "../config";

interface CountySoilData {
  date: string;       
  year: number;       
  county: string;     
  sm_mean_m3m3: number;
  valid_days: number;
  n_pixels: number;   
}

export default function SMAPAnnualMeansAllCounties() {
  const [allData, setAllData] = useState<CountySoilData[]>([]);
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    axios.get<CountySoilData[]>(`${DATA_BASE_URL}/smap_annual_means.json`)
      .then(res => { setAllData(res.data); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  if (loading) return <div>Loading environmental data...</div>;

  // 1. Extract unique, alphabetically sorted county names
  const counties = Array.from(new Set(allData.map(item => item.county))).sort();

  // 2. Generate a separate trace for every single county dynamically
  const traces = counties.map(countyName => {
    // Filter rows belonging to this specific county
    const countyRecords = allData.filter(row => row.county === countyName);
    
    // Sort chronological data by year to prevent zig-zag rendering lines
    const sortedRecords = countyRecords.sort((a, b) => a.year - b.year);

    return {
      x: sortedRecords.map(row => row.year),
      y: sortedRecords.map(row => row.sm_mean_m3m3),
      type: 'scatter' as const,
      mode: 'lines+markers' as const,
      name: countyName, // This value text populates your chart legend names automatically
      marker: { size: 6 },
      line: { width: 2 } // Plotly assigns distinct color palettes to traces by default
    };
  });

  return (
    <section style={{ padding: "1.5rem 2rem", fontFamily: 'sans-serif' }}>
      <h2 style={{ color: "#1b4332", marginBottom: "1.5rem" }}>
        Soil Moisture Trends Across Central Virginia Counties
      </h2>
      
      <div style={{ overflowX: 'auto' }}>
        <Plot
          data={traces} // Pass the entire generated array of traces here
          layout={{
            title: { text: "Annual Mean Soil Moisture Comparison" },
            xaxis: { 
              title: { text: "Year" },
              tickmode: "linear", 
              dtick: 1
            },
            yaxis: { title: { text: "Soil Moisture (m³/m³)" }, range: [0.1, 0.45] },
            width: 960, // Widened layout canvas slightly to give your new legend clean spacing
            height: 450,
            margin: { t: 50, l: 60, r: 150, b: 50 }, // Expanded right padding (r) so long county words do not clip
            showlegend: true, // Guarantees the dynamic sidebar legend panel renders
            legend: {
              x: 1.05, // Shifts panel comfortably just outside the main grid frame boundary
              y: 1,
              traceorder: 'normal',
              font: { size: 12 }
            }
          }}
          config={{ responsive: true }}
        />
      </div>

      <p style={{ fontSize: "0.8rem", color: "#555", marginTop: "1rem" }}>
        Source: NASA SMAP SPL3SMP_E v006 · AM overpass · 9 km resolution ·
        💡 Tip: Click individual counties in the legend on the right to toggle their visibility on the chart.
      </p>
    </section>
  );
}
