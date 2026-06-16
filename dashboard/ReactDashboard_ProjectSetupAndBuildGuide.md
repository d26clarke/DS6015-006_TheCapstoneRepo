# React Dashboard — Project Setup and Build Guide

## Prerequisites

You need **Node.js 18+** and **npm** installed. Verify with:

```bash
node --version   # should be v18.x or higher
npm --version    # should be 9.x or higher
```

If Node.js is not installed, download it from [https://nodejs.org](https://nodejs.org) (LTS version).

---

## Step 1 — Scaffold the Project

Run this once from your working directory (e.g., your home folder or `~/development/react_projects/`):

```bash
npm create vite@latest central-va-tree-canopy-dashboard -- --template react-ts
```

Vite will ask a few questions — accept the defaults. This creates the folder
`central-va-tree-canopy-dashboard/` with a complete React + TypeScript starter project.

---

## Step 2 — Install Dependencies

```bash
cd central-va-tree-canopy-dashboard
npm install
```

Then install the charting and HTTP libraries the dashboard components use:

```bash
npm install plotly.js react-plotly.js axios
npm install --save-dev @types/plotly.js

After initial tests, we need to use the following...

npm install react-plotly.js plotly.js-dist-min axios
npm install --save-dev @types/react-plotly.js @types/plotly.js 
npm install --save-dev @types/plotly.js-dist-min

Then, we need to create the factory component...

Instead of importing the default react-plotly.js component directly (which can sometimes pull in the standard non-minified version), it is highly recommended to manually instantiate a factory component using the safe plotly.js-dist-min bundle:

// src/components/Chart.tsx
import Plotly from 'plotly.js-dist-min';
import createPlotlyComponent from 'react-plotly.js/factory';

// Create the custom safe React wrapper
const Plot = createPlotlyComponent(Plotly);

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
        title: title,
        autosize: true,
        useResizeHandler: true, // Crucial for responsive grid widths
      }}
      style={{ width: "100%", height: "400px" }}
    />
  );
}

Then, to use the component...

// src/App.tsx
import Chart from './components/Chart';

function App() {
  return (
    <div style={{ maxWidth: '800px', margin: '0 auto', padding: '20px' }}>
      <h1>Vite + React Plotly Dashboard</h1>
      <Chart title="Quarterly Metrics Performance" />
    </div>
  );
}

export default App;


```

Your `package.json` dependencies section should now include:

| Package | Purpose |
| :--- | :--- |
| `plotly.js` | Core Plotly charting engine |
| `react-plotly.js` | React wrapper for Plotly |
| `axios` | HTTP client for fetching JSON from S3 |
| `@types/plotly.js` | TypeScript type definitions for Plotly |

---

## Step 3 — Create the Project Files

Create the following directory structure under `src/`:

```
src/
├── config.ts                    ← data URL switcher
├── App.tsx                      ← root layout
└── components/
    ├── Header.tsx
    ├── SMAPTimeSeries.tsx
    ├── CanopyCoverBar.tsx
    └── Footer.tsx
```

Copy each component from `2_react_dashboard.tsx` (removing the `/* */` comment
wrappers) into the corresponding file. The component file already contains all
five files clearly delimited by `// FILE:` comments.

---

## Step 4 — Add Local Test Data

For local development, create a `public/data/` folder and copy your exported
JSON files into it so the app can fetch them without hitting S3:

```bash
mkdir -p public/data
cp ../dashboard_exports/smap_annual_means.json  public/data/
cp ../dashboard_exports/canopy_summary.json     public/data/
cp ../dashboard_exports/metadata.json           public/data/
```

The `config.ts` file already points to `/data` in development mode, so the
app will read from `public/data/` automatically when running locally.

---

## Step 5 — Run the Development Server

```bash
npm run dev
```
 
Vite starts a local server at `http://localhost:5173`. Open that URL in your
browser. The dashboard will hot-reload whenever you save a file — no manual
refresh needed.

---

## Step 6 — Update the Production Data URL

After deploying to CloudFront (Step 3 of `3_aws_deployment.sh`), you will
receive a domain like `dXXXXXXXXXXXXX.cloudfront.net`. Open `src/config.ts`
and replace the placeholder:

```typescript
// src/config.ts
const DATA_BASE_URL =
  import.meta.env.PROD
    ? "https://dXXXXXXXXXXXXX.cloudfront.net/data"  // ← your domain
    : "/data";

export default DATA_BASE_URL;
```

---

## Step 7 — Build for Production

```bash
npm run build
```

Vite compiles, minifies, and tree-shakes the entire app into the `dist/`
folder. The output looks like this:

```
dist/
├── index.html                   ← entry point
└── assets/
    ├── index-BxYz1234.js        ← hashed JS bundle (~300–500 KB gzipped)
    └── index-AbCd5678.css       ← hashed CSS bundle
```

The hash in each filename changes whenever the file content changes — this
enables aggressive browser caching (1-year `max-age`) without stale content.

---

## Step 8 — Preview the Production Build Locally

Before uploading to S3, verify the production build works correctly:

```bash
npm run preview
```

This serves the `dist/` folder at `http://localhost:4173`. Confirm all charts
load and the methodology link resolves correctly.

---

## Step 9 — Deploy to S3

Once satisfied with the preview, run the deployment script:

```bash
bash ../3_aws_deployment.sh
```

Or manually sync:

```bash
aws s3 sync dist/ s3://central-va-tree-canopy-dashboard --delete --cache-control "max-age=31536000,immutable"

aws s3 cp dist/index.html s3://central-va-tree-canopy-dashboard/index.html --cache-control "no-cache,no-store,must-revalidate" --content-type "text/html"

```

---

## Step 10 — Invalidate CloudFront Cache After Updates

Every time you redeploy, invalidate the CloudFront cache so visitors see the
latest version immediately:

```bash
# Replace DISTRIBUTION_ID with your actual ID from Step D of the deployment script

aws cloudfront create-invalidation --distribution-id E3KTCRUHT8MSD4 --paths "/*"

```

---

## Common Errors and Fixes

| Error | Cause | Fix |
| :--- | :--- | :--- |
| `Cannot find module 'react-plotly.js'` | Package not installed | Run `npm install react-plotly.js plotly.js` |
| `AxiosError: Network Error` | CORS not set on data bucket | Run Step C of `3_aws_deployment.sh` |
| Charts render but show no data | JSON path in `config.ts` is wrong | Verify `DATA_BASE_URL` matches your S3/CloudFront path |
| `npm run build` fails with TS errors | Missing `@types/plotly.js` | Run `npm install --save-dev @types/plotly.js` |
| Blank page on CloudFront | `index.html` not set as error document | Verify CloudFront `CustomErrorResponse` 404 → `/index.html` |

---

## Full Command Reference

```bash
npm create vite@latest cville-canopy-dashboard -- --template react-ts
cd cville-canopy-dashboard
npm install
npm install plotly.js react-plotly.js axios
npm install --save-dev @types/plotly.js
npm run dev          # local development server at localhost:5173
npm run build        # production build → dist/
npm run preview      # preview production build at localhost:4173
```
