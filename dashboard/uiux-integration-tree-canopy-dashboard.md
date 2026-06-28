# Split-Panel Dashboard — Integration Guide

## Files Delivered

| File | Purpose |
|---|---|
| `SplitPanelDashboard.tsx` | Main split-panel component (map + chart) |
| `LagLegend.tsx` | Color-scale legend overlay for the choropleth map |
| `colorScale.ts` | Color ramp utilities — `valueToColor`, `buildLegendStops`, `computeDomain` |
| `types.ts` | Shared TypeScript interfaces and constants |
| `INTEGRATION.md` | This file |

---

## Step 1 — Install Dependencies

```bash
# Core map and chart libraries
npm install leaflet react-leaflet recharts axios

# TypeScript types
npm install -D @types/leaflet @types/geojson
```

---

## Step 2 — Import Leaflet CSS

In your `main.tsx` or `App.tsx`, add this import **before** any component imports:

```tsx
import "leaflet/dist/leaflet.css";
```

---

## Step 3 — Fix Leaflet Default Marker Icons (Vite-specific)

Vite's asset pipeline breaks Leaflet's default marker icon paths. Add this
to `main.tsx` after the Leaflet CSS import:

```tsx
import L from "leaflet";
import markerIcon2x from "leaflet/dist/images/marker-icon-2x.png";
import markerIcon   from "leaflet/dist/images/marker-icon.png";
import markerShadow from "leaflet/dist/images/marker-shadow.png";

delete (L.Icon.Default.prototype as any)._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: markerIcon2x,
  iconUrl:       markerIcon,
  shadowUrl:     markerShadow,
});
```

---

## Step 4 — Upload GeoJSON Files to S3

The component expects one GeoJSON boundary file per jurisdiction at these S3 keys
(relative to `DATA_BASE_URL`):

```
geojson/CityOfCharlottesville.geojson   ← already available (attached)
geojson/Albemarle.geojson
geojson/Augusta.geojson
geojson/Fluvanna.geojson
geojson/Greene.geojson
geojson/Louisa.geojson
geojson/Nelson.geojson
geojson/Rockingham.geojson
```

Upload command (repeat for each file):

```bash
aws s3 cp CityOfCharlottesville.geojson \
  s3://central-va-tree-canopy-dashboard/geojson/CityOfCharlottesville.geojson \
  --content-type "application/geo+json"
```

**Important:** The Charlottesville GeoJSON uses 4D coordinates
`[lon, lat, elevation, null]`. Leaflet only reads the first two values
(lon, lat) and ignores the rest — no preprocessing is required.

---

## Step 5 — Verify S3 CORS Configuration

The dashboard fetches GeoJSON and JSON files directly from S3 via Axios.
Your `central-va-tree-canopy-dashboard` bucket must have a CORS rule that
allows `GET` requests from your CloudFront domain:

```json
[
  {
    "AllowedHeaders": ["*"],
    "AllowedMethods": ["GET", "HEAD"],
    "AllowedOrigins": ["https://dqs7zvzytpj1t.cloudfront.net"],
    "ExposeHeaders": [],
    "MaxAgeSeconds": 3000
  }
]
```

Apply it:
```bash
aws s3api put-bucket-cors \
  --bucket central-va-tree-canopy-dashboard \
  --cors-configuration file://cors.json
```

---

## Step 6 — Use the Component

```tsx
// In App.tsx or a route component:
import SplitPanelDashboard from "./dashboard/SplitPanelDashboard";

export default function App() {
  return <SplitPanelDashboard />;
}
```

The component is self-contained and manages all its own data fetching and state.

---

## Data Schema Reference

### `merged_smap_gedi02B.json` fields used

| Field | Type | Used for |
|---|---|---|
| `jurisdiction` | string | GeoJSON merge key |
| `year` | number | Year filter dropdown |
| `mean_canopy_cover` | number (0–1) | Choropleth + canopy chart |
| `sm_mean_m3m3` | number | Choropleth + SM chart |
| `sm_mean_lag1` | number \| null | Choropleth + lag lines |
| `sm_mean_lag2` | number \| null | Choropleth + lag lines |

### `smap_timeseries.json` fields used

| Field | Type | Used for |
|---|---|---|
| `year` | number | X-axis (2015–2023) |
| `sm_mean` | number | Regional SM baseline line |
| `sm_min` | number | Available for error band (not rendered by default) |
| `sm_max` | number | Available for error band (not rendered by default) |

---

## Choropleth Color Scales

| Metric | Ramp | Low → High |
|---|---|---|
| Canopy Cover | Sequential green | Pale green → Forest green |
| Soil Moisture (same year) | Sequential blue | Pale blue → Deep blue |
| SM Lag-1 | Diverging blue-orange | Orange → Purple |
| SM Lag-2 | Diverging blue-orange | Orange → Purple |

The lag fields use a **diverging** ramp to visually distinguish them from
same-year soil moisture and to highlight jurisdictions where the lagged
signal is anomalously high or low relative to the study-area mean.

---

## Known Limitations

- Charlottesville has no 2020 or 2023 GEDI observations — its polygon
  will render in grey (`#cccccc`) for those year/metric combinations.
- The 2019 SMAP value represents only 32 days (Jan–Feb). A `⚠` note is
  rendered below the charts.
- Lag fields are `null` for the first 1–2 years of each jurisdiction's
  record by construction (`.shift()` introduces NaN at the head of each group).
