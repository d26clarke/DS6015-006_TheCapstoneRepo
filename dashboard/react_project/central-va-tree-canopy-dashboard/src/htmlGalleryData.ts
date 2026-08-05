// ─── htmlGalleryData.ts ──────────────────────────────────────────────────────
// Static manifest of the visualization HTML files under
// s3://central-va-tree-canopy-dashboard/data/html-files/visualizations/
//
// These are full standalone HTML documents (nbconvert/Plotly-style exports
// with their own <html>/<head>/<body>, embedded stylesheets, and scripts) --
// NOT lightweight fragments. They must be rendered via <iframe>, never
// injected directly into the page, or their styles/scripts would collide
// with the dashboard's own.
//
// This is a static, hardcoded manifest rather than a live S3 ListObjectsV2
// call, matching how other fixed lists (e.g. COUNTIES) already work
// elsewhere in this dashboard -- avoids needing new bucket permissions/CORS
// just to enumerate ~40 known, rarely-changing files.

import DATA_BASE_URL from "./config";

export type Product = "canopy_height" | "canopy_cover";

export interface VisualEntry {
  product: Product;
  visualNumber: number;
  label: string;
  /** Sub-area variant, or null for the region-wide version. */
  subArea: string | null;
  filename: string;
}

const PRODUCT_FOLDER: Record<Product, string> = {
  canopy_height: "smap_gedi_output",
  canopy_cover: "smap_gedi02B_output",
};

export const PRODUCT_LABELS: Record<Product, string> = {
  canopy_height: "Canopy Height (SMAP + GEDI Level 2A)",
  canopy_cover: "Canopy Cover (SMAP + GEDI Level 2B)",
};

// Sub-area labels are inferred from the abbreviated codes in the actual S3
// filenames (route29north, rviewpark, rwatershed) -- confirm/correct these
// against your own naming intent, since they're a best-effort expansion,
// not sourced from an authoritative label list.
export const SUB_AREA_LABELS: Record<string, string> = {
  route29north: "Route 29 North Corridor",
  rviewpark: "River View Park",
  rwatershed: "Rivanna Watershed",
};

const VISUAL_LABELS: Record<number, string> = {
  1: "SMAP Soil Moisture Time Series",
  2: "GEDI Canopy Cover / Height Bars",
  3: "Dual-Axis Facet (Canopy vs. Soil Moisture)",
  4: "Scatter Correlation",
  5: "Lag Regression Panels",
  6: "Pearson Correlation Heatmap",
  7: "Regional Dual-Axis Summary",
};

export const GALLERY_ENTRIES: VisualEntry[] = [
  // ── canopy_height (smap_gedi_output) -- 7 visual types x 4 areas (region + 3 sub-areas) ──
  { product: "canopy_height", visualNumber: 1, label: VISUAL_LABELS[1], subArea: null, filename: "visual1_smap_timeseries.html" },
  { product: "canopy_height", visualNumber: 1, label: VISUAL_LABELS[1], subArea: "route29north", filename: "visual1_smap_timeseries-route29north.html" },
  { product: "canopy_height", visualNumber: 1, label: VISUAL_LABELS[1], subArea: "rviewpark", filename: "visual1_smap_timeseries-rviewpark.html" },
  { product: "canopy_height", visualNumber: 1, label: VISUAL_LABELS[1], subArea: "rwatershed", filename: "visual1_smap_timeseries-rwatershed.html" },

  { product: "canopy_height", visualNumber: 2, label: VISUAL_LABELS[2], subArea: null, filename: "visual2_gedi_canopy_bars.html" },
  { product: "canopy_height", visualNumber: 2, label: VISUAL_LABELS[2], subArea: "route29north", filename: "visual2_gedi_canopy_bars-route29north.html" },
  { product: "canopy_height", visualNumber: 2, label: VISUAL_LABELS[2], subArea: "rviewpark", filename: "visual2_gedi_canopy_bars-rviewpark.html" },
  { product: "canopy_height", visualNumber: 2, label: VISUAL_LABELS[2], subArea: "rwatershed", filename: "visual2_gedi_canopy_bars-rwatershed.html" },

  { product: "canopy_height", visualNumber: 3, label: VISUAL_LABELS[3], subArea: null, filename: "visual3_dual_axis_facet.html" },
  { product: "canopy_height", visualNumber: 3, label: VISUAL_LABELS[3], subArea: "route29north", filename: "visual3_dual_axis_facet-route29north.html" },
  { product: "canopy_height", visualNumber: 3, label: VISUAL_LABELS[3], subArea: "rviewpark", filename: "visual3_dual_axis_facet-rviewpark.html" },
  { product: "canopy_height", visualNumber: 3, label: VISUAL_LABELS[3], subArea: "rwatershed", filename: "visual3_dual_axis_facet-rwatershed.html" },

  { product: "canopy_height", visualNumber: 4, label: VISUAL_LABELS[4], subArea: null, filename: "visual4_scatter_correlation.html" },
  { product: "canopy_height", visualNumber: 4, label: VISUAL_LABELS[4], subArea: "route29north", filename: "visual4_scatter_correlation-route29north.html" },
  { product: "canopy_height", visualNumber: 4, label: VISUAL_LABELS[4], subArea: "rviewpark", filename: "visual4_scatter_correlation-rviewpark.html" },
  { product: "canopy_height", visualNumber: 4, label: VISUAL_LABELS[4], subArea: "rwatershed", filename: "visual4_scatter_correlation-rwatershed.html" },

  { product: "canopy_height", visualNumber: 5, label: VISUAL_LABELS[5], subArea: null, filename: "visual5_lag_regression_panels.html" },
  { product: "canopy_height", visualNumber: 5, label: VISUAL_LABELS[5], subArea: "route29north", filename: "visual5_lag_regression_panels-route29north.html" },
  { product: "canopy_height", visualNumber: 5, label: VISUAL_LABELS[5], subArea: "rviewpark", filename: "visual5_lag_regression_panels-rviewpark.html" },
  { product: "canopy_height", visualNumber: 5, label: VISUAL_LABELS[5], subArea: "rwatershed", filename: "visual5_lag_regression_panels-rwatershed.html" },

  { product: "canopy_height", visualNumber: 6, label: VISUAL_LABELS[6], subArea: null, filename: "visual6_pearson_heatmap.html" },
  { product: "canopy_height", visualNumber: 6, label: VISUAL_LABELS[6], subArea: "route29north", filename: "visual6_pearson_heatmap-route29north.html" },
  { product: "canopy_height", visualNumber: 6, label: VISUAL_LABELS[6], subArea: "rviewpark", filename: "visual6_pearson_heatmap-rviewpark.html" },
  { product: "canopy_height", visualNumber: 6, label: VISUAL_LABELS[6], subArea: "rwatershed", filename: "visual6_pearson_heatmap-rwatershed.html" },

  { product: "canopy_height", visualNumber: 7, label: VISUAL_LABELS[7], subArea: null, filename: "visual7_regional_dual_axis.html" },
  { product: "canopy_height", visualNumber: 7, label: VISUAL_LABELS[7], subArea: "route29north", filename: "visual7_regional_dual_axis-route29north.html" },
  { product: "canopy_height", visualNumber: 7, label: VISUAL_LABELS[7], subArea: "rviewpark", filename: "visual7_regional_dual_axis-rviewpark.html" },
  { product: "canopy_height", visualNumber: 7, label: VISUAL_LABELS[7], subArea: "rwatershed", filename: "visual7_regional_dual_axis-rwatershed.html" },

  // ── canopy_cover (smap_gedi02B_output) -- each visual type has TWO filenames,
  // likely the same content under two naming conventions from different
  // pipeline runs. Both are listed rather than silently dropping one, since
  // this can't be verified without fetching the files directly. ──────────
  { product: "canopy_cover", visualNumber: 1, label: VISUAL_LABELS[1] + " (A)", subArea: null, filename: "visual1_smap_timeseries.html" },
  { product: "canopy_cover", visualNumber: 1, label: VISUAL_LABELS[1] + " (B)", subArea: null, filename: "visual1_smap-gedi02B_timeseries.html" },

  { product: "canopy_cover", visualNumber: 2, label: VISUAL_LABELS[2] + " (A)", subArea: null, filename: "visual2_gedi_canopy_bars.html" },
  { product: "canopy_cover", visualNumber: 2, label: VISUAL_LABELS[2] + " (B)", subArea: null, filename: "visual2_gedi02B_canopy_bars.html" },

  { product: "canopy_cover", visualNumber: 3, label: VISUAL_LABELS[3] + " (A)", subArea: null, filename: "visual3_dual_axis_facet.html" },
  { product: "canopy_cover", visualNumber: 3, label: VISUAL_LABELS[3] + " (B)", subArea: null, filename: "visual3_dual_axis-gedi02B_facet.html" },

  { product: "canopy_cover", visualNumber: 4, label: VISUAL_LABELS[4] + " (A)", subArea: null, filename: "visual4_scatter_correlation.html" },
  { product: "canopy_cover", visualNumber: 4, label: VISUAL_LABELS[4] + " (B)", subArea: null, filename: "visual4-gedi02B_scatter_correlation.html" },

  { product: "canopy_cover", visualNumber: 5, label: VISUAL_LABELS[5] + " (A)", subArea: null, filename: "visual5_lag_regression_panels.html" },
  { product: "canopy_cover", visualNumber: 5, label: VISUAL_LABELS[5] + " (B)", subArea: null, filename: "visual5-gedi02B_lag_regression_panels.html" },

  { product: "canopy_cover", visualNumber: 6, label: VISUAL_LABELS[6] + " (A)", subArea: null, filename: "visual6_pearson_heatmap.html" },
  { product: "canopy_cover", visualNumber: 6, label: VISUAL_LABELS[6] + " (B)", subArea: null, filename: "visual6-gedi02B_pearson_heatmap.html" },

  { product: "canopy_cover", visualNumber: 7, label: VISUAL_LABELS[7] + " (A)", subArea: null, filename: "visual7_regional_dual_axis.html" },
  { product: "canopy_cover", visualNumber: 7, label: VISUAL_LABELS[7] + " (B)", subArea: null, filename: "visual7-gedi02B_regional_dual_axis.html" },
];

export function galleryEntryUrl(entry: VisualEntry): string {
  const folder = PRODUCT_FOLDER[entry.product];
  return `${DATA_BASE_URL}/html-files/visualizations/${folder}/${entry.filename}`;
}
