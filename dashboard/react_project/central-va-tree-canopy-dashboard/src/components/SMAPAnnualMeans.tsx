import React, { useEffect, useState } from 'react';
import { CountySoilData } from './types';

const SoilMoistureDashboard: React.FC = () => {
  const [allData, setAllData] = useState<CountySoilData[]>([]);
  const [selectedCounty, setSelectedCounty] = useState<string>('Albemarle');
  const [loading, setLoading] = useState<boolean>(true);

  // Dynamic URL selection for local dev vs production S3
  const baseUrl: string = import.meta.env.DEV 
    ? '/data' 
    : 'https://amazonaws.com';

  useEffect(() => {
    // Fetches your environmental JSON dataset
    fetch(`${baseUrl}/soil_moisture.json`)
      .then((res) => res.json())
      .then((data: CountySoilData[]) => {
        setAllData(data);
        setLoading(false);
      })
      .catch((err) => console.error("Error loading soil data:", err));
  }, [baseUrl]);

  // Extract unique county names to build a dropdown filter
  const counties = Array.from(new Set(allData.map(item => item.county)));

  // Filter dataset down to the chosen county
  const filteredData = allData.filter(item => item.county === selectedCounty);

  if (loading) return <div>Loading environmental data...</div>;

  return (
    <div style={{ padding: '20px', fontFamily: 'sans-serif' }}>
      <h2>Central VA Soil Moisture Metrics</h2>
      
      {/* Dropdown menu to swap counties */}
      <label htmlFor="county-select">Select County: </label>
      <select 
        id="county-select"
        value={selectedCounty} 
        onChange={(e) => setSelectedCounty(e.target.value)}
        style={{ padding: '5px', marginBottom: '20px' }}
      >
        {counties.map(county => (
          <option key={county} value={county}>{county}</option>
        ))}
      </select>

      {/* Render a table of the records for the chosen county */}
      <table border={1} cellPadding={8} style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr style={{ backgroundColor: '#f2f2f2' }}>
            <th>Year</th>
            <th>Soil Moisture Mean (m³/m³)</th>
            <th>Valid Days</th>
            <th>Pixels</th>
          </tr>
        </thead>
        <tbody>
          {filteredData.map((row, index) => (
            <tr key={index}>
              <td>{row.year}</td>
              {/* Limit floating points to 4 decimals for clean UI reading */}
              <td>{row.sm_mean_m3m3.toFixed(4)}</td>
              <td>{Math.round(row.valid_days)}</td>
              <td>{row.n_pixels}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

export default SoilMoistureDashboard;

