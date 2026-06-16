import Plotly from 'plotly.js-dist-min';
import _createPlotlyComponent from 'react-plotly.js/factory';

const createPlotlyComponent =
  (_createPlotlyComponent as { default?: any }).default ?? _createPlotlyComponent;
 
// Create the custom safe React wrapper
const Plot = createPlotlyComponent(Plotly as any);
//const Plot = createPlotlyComponent.default ? createPlotlyComponent.default(Plotly) : createPlotlyComponent(Plotly);

interface ChartProps {
  title: string;
}

export default function Chart({ title }: ChartProps) {
  return (
    <Plot
      data={[
        {
          x: [1, 2, 3, 4],
          y: [10, 15, 13, 17],
          type: 'scatter',
          mode: 'lines+markers',
          marker: { color: '#3b82f6' },
        },
        {
          type: 'bar',
          x: [1, 2, 3, 4],
          y: [12, 9, 15, 11],
          marker: { color: '#10b981' },
        },
      ]}
      layout={{
        title: { text: title},
        autosize: true,
        margin: { t: 50, b: 50, l: 50, r: 50 },
      }}
      
      useResizeHandler={true}   // Crucial for recalculating size on window resize
      style={{ width: "100%", height: "400px" }}
      config={{ responsive: true }} // Recommended for modern Plotly behavior
    />
  );
}