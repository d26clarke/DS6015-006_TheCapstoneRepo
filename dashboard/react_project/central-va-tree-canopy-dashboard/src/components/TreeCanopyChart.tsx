// 1. Safe factory initialization for Vite compatibility
import Plotly from 'plotly.js-dist-min';
import _createPlotlyComponent from 'react-plotly.js/factory';

const createPlotlyComponent =
  (_createPlotlyComponent as { default?: any }).default ?? _createPlotlyComponent;
 
const Plot = createPlotlyComponent(Plotly as any);

import { useEffect, useState } from "react";
import axios from "axios";
import DATA_BASE_URL from "../config"; // Points to your S3 bucket endpoint in production

// --- TypeScript Interfaces ---
interface PlotlyDataElement {
  type: string;
  x?: (string | number)[];
  y?: (string | number)[];
  z?: (string | number)[][];
  mode?: string;
  marker?: Record<string, any>;
  [key: string]: any; 
}

interface PlotlyPayload {
  data: PlotlyDataElement[];
  layout: Record<string, any>;
}

export default function TreeCanopyChart() {
  const [chartData, setChartData] = useState<PlotlyPayload | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    // Fetches directly from your AWS S3 bucket endpoint via config base URL
    axios.get<PlotlyPayload>(`${DATA_BASE_URL}/canopy_cover_bar.json`)
      .then((res) => {
        setChartData(res.data);
        setLoading(false);
      })
      .catch((err) => {
        console.error("Error fetching canopy data from S3:", err);
        setLoading(false);
      });
  }, []);

  // Safety Gate 1: Prevents 'undefined' errors while Axios fetches network data
  if (loading) {
    return <div style={{ padding: "2rem", fontFamily: 'sans-serif' }}>Loading Canopy Data...</div>;
  }

  // Safety Gate 2: Fallback if the file is blank or formatted incorrectly
  if (!chartData || !chartData.layout || !chartData.data) {
    return (
      <div style={{ padding: "2rem", color: "red", fontFamily: 'sans-serif' }}>
        Error parsing tree canopy data file from S3 storage.
      </div>
    );
  }

  return (
    <section style={{ padding: "1.5rem 2rem", fontFamily: 'sans-serif' }}>
      <h2 style={{ color: "#1b4332", marginBottom: "0.5rem" }}>
        Central VA Tree Canopy Coverage
      </h2>

      <div style={{ overflowX: 'auto', backgroundColor: '#fff', borderRadius: '8px', padding: '1rem' }}>
        <Plot
          // References the live-fetched S3 object structure
          data={chartData.data}
          layout={{
            ...chartData.layout,
            width: 860,
            height: 400,
            margin: { t: 50, l: 60, r: 20, b: 50 }
          }}
          config={{ responsive: true }}
        />
      </div>
    </section>
  );
}
