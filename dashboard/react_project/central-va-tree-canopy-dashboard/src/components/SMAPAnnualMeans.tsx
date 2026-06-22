import Plotly from 'plotly.js-dist-min';
import _createPlotlyComponent from 'react-plotly.js/factory';

const createPlotlyComponent =
  (_createPlotlyComponent as { default?: any }).default ?? _createPlotlyComponent;
 
// Create the custom safe React wrapper
const Plot = createPlotlyComponent(Plotly as any);

import { useEffect, useState } from "react";

import axios from "axios";

import DATA_BASE_URL from "../config";

interface CountySoilData {
  date: string;       // Matches "2015-01-01"
  year: number;       // Matches 2015 (Note: this is a number, not a string)
  county: string;     // Matches "Albemarle", "Augusta", etc.
  sm_mean_m3m3: number;
  valid_days: number;
  n_pixels: number;   // Matches 33
}

export default function SMAPAnnualMeans() {
  
  const [allData, setAllData] = useState<CountySoilData[]>([]);
  //const [selectedCounty, setSelectedCounty] = useState<string>('Albemarle');
  
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    axios.get<CountySoilData[]>(`${DATA_BASE_URL}/smap_annual_means.json`)
      .then(res => { setAllData(res.data); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);


  // Extract unique county names to build a dropdown filter
  const counties = Array.from(new Set(allData.map(item => item.county)));

  //const [selectedCounty, setSelectedCounty] = useState(counties[0] || '');

  const [selectedCounty, setSelectedCounty] = useState<string>(counties[0]);

  // Filter dataset down to the chosen county
  const filteredData = allData.filter(item => item.county === selectedCounty);

  // Build the Plotly trace dynamically using array maps from your filtered data
  const trace = {
    x: filteredData.map(row => row.year),
    y: filteredData.map(row => row.sm_mean_m3m3),
    type: 'scatter', // Creates a line/scatter plot
    mode: 'lines+markers', // Shows lines with clickable dots
    line: { color: '#1b4332', width: 2 }, // Matches your green theme color
    marker: { size: 6 },
    name: selectedCounty
  };

  if (loading) return <div>Loading environmental data...</div>;

  return (
    <section style={{ padding: "1.5rem 2rem", fontFamily: 'sans-serif' }}>
      <h2 style={{ color: "#1b4332", marginBottom: "0.5rem" }}>
        Soil Moisture Trend (SMAP SPL3SMP_E)
      </h2>
      
      {/* Retained and styled your original dropdown menu */}
      <div style={{ marginBottom: '1.5rem' }}>
        <label htmlFor="county-select" style={{ fontWeight: 'bold', marginRight: '8px' }}>
          Select County:{" "}
        </label>
        <select 
          id="county-select"
          value={selectedCounty} 
          onChange={(e) => setSelectedCounty(e.target.value)}
          style={{ padding: '6px 12px', borderRadius: '4px', border: '1px solid #ccc' }}
        >
          {counties.map(county => (
            <option key={county} value={county}>{county}</option>
          ))}
        </select>
      </div>

      {/* 3. Render your requested Plotly layout */}
      <div style={{ overflowX: 'auto' }}>
        <Plot
          data={[trace]}
          layout={{
            title: { text: `Annual Mean Soil Moisture — ${selectedCounty} County` },
            xaxis: { 
              title: { text: "Year" },
              tickmode: "linear", // Prevents the browser from displaying fractional years (e.g., 2021.5)
              dtick: 1
            },
            yaxis: { title: { text: "Soil Moisture (m³/m³)" }, range: [0.1, 0.4] },
            width: 860, 
            height: 400,
            margin: { t: 50, l: 60, r: 20, b: 50 }
          }}
          config={{ responsive: true }}
        />
      </div>

      <p style={{ fontSize: "0.8rem", color: "#555", marginTop: "1rem" }}>
        Source: NASA SMAP SPL3SMP_E v006 · AM overpass · 9 km resolution ·
        Bbox: Charlottesville + Albemarle + Buckingham + Fluvanna + Greene + Nelson + Orange + Louisa
      </p>
    </section>
  );

}

