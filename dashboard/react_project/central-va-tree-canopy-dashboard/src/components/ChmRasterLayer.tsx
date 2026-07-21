// ─── ChmRasterLayer.tsx ──────────────────────────────────────────────────────
//
// Overlays a Canopy Height Model (CHM) GeoTIFF -- output of the LiDAR
// processing pipeline (sagemaker_process_lidar.py, *_chm.tif per tile) --
// on the existing Leaflet map as a colorized raster layer.
//
// This is a plain Leaflet layer (georaster-layer-for-leaflet extends
// L.GridLayer), so -- same as the other map layers in this dashboard --
// it's added/removed imperatively via the underlying map instance rather
// than through a react-leaflet wrapper component.
//
// Data contract:
//   A single-band Float32 GeoTIFF, height-above-ground in meters, in the
//   pipeline's OUTPUT_CRS (a meters-based Virginia State Plane CRS -- see
//   CHM_SOURCE_CRS_EPSG / CHM_SOURCE_CRS_PROJ4 below, which must match
//   whatever OUTPUT_CRS the pipeline actually used).
//
// Dependencies to add to package.json:
//   npm install georaster georaster-layer-for-leaflet proj4
//   npm install -D @types/proj4
//
// ─────────────────────────────────────────────────────────────────────────────

import { useEffect, useRef, useState } from "react";
import { useMap } from "react-leaflet";
import type L from "leaflet";
import axios from "axios";
import proj4 from "proj4";
// @ts-expect-error -- georaster ships without types
import parseGeoraster from "georaster";
import GeoRasterLayer from "georaster-layer-for-leaflet";

import DATA_BASE_URL from "../config";

// ── Source CRS registration ──────────────────────────────────────────────────
// Placeholder for Virginia State Plane South (meters) -- replace with
// whatever OUTPUT_CRS your sagemaker_process_lidar.py run actually used.
// Get the exact proj4 string for any EPSG code from https://epsg.io/<code>.
export const CHM_SOURCE_CRS_EPSG = "EPSG:6591";
export const CHM_SOURCE_CRS_PROJ4 =
  "+proj=lcc +lat_1=37.96666666666667 +lat_2=36.76666666666667 +lat_0=36.33333333333334 " +
  "+lon_0=-78.5 +x_0=3500000 +y_0=1000000 +ellps=GRS80 +units=m +no_defs";

proj4.defs(CHM_SOURCE_CRS_EPSG, CHM_SOURCE_CRS_PROJ4);

// ── Canopy height color ramp ─────────────────────────────────────────────────
// Reuses this dashboard's existing forest-green family (see JURIS_COLORS in
// SplitPanelDashboard.tsx) so the raster reads as part of the same visual
// system rather than introducing a new palette.
const HEIGHT_GRADIENT: Array<[number, string]> = [
  [0.0, "#2a1f14"], // bare ground
  [0.15, "#40916c"],
  [0.4, "#52b788"],
  [0.7, "#74c69d"],
  [1.0, "#d8f3dc"], // tallest canopy
];

export const MIN_CANOPY_HEIGHT_M = 2.0;
export const MAX_CANOPY_HEIGHT_M = 60.0;

function hexToRgb(hex: string) {
  const n = parseInt(hex.replace("#", ""), 16);
  return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 };
}

function lerpColor(a: string, b: string, t: number): string {
  const pa = hexToRgb(a);
  const pb = hexToRgb(b);
  const r = Math.round(pa.r + (pb.r - pa.r) * t);
  const g = Math.round(pa.g + (pb.g - pa.g) * t);
  const bch = Math.round(pa.b + (pb.b - pa.b) * t);
  return `rgb(${r},${g},${bch})`;
}

export function heightToColor(h: number, max: number = MAX_CANOPY_HEIGHT_M): string {
  const t = Math.max(0, Math.min(1, h / max));
  for (let i = 1; i < HEIGHT_GRADIENT.length; i++) {
    const [stopLo, colorLo] = HEIGHT_GRADIENT[i - 1];
    const [stopHi, colorHi] = HEIGHT_GRADIENT[i];
    if (t <= stopHi) {
      const localT = (t - stopLo) / (stopHi - stopLo || 1);
      return lerpColor(colorLo, colorHi, localT);
    }
  }
  return HEIGHT_GRADIENT[HEIGHT_GRADIENT.length - 1][1];
}

// ── Props ─────────────────────────────────────────────────────────────────────
interface ChmRasterLayerProps {
  /** S3 key (relative to DATA_BASE_URL) for the tile's *_chm.tif, e.g.
   *  "lidar/Charlottesville/geotiff/S13_4889_10_chm.tif" */
  s3Key: string;
  opacity?: number;
  onError?: (message: string) => void;
  onBoundsReady?: (bounds: L.LatLngBounds) => void;
}

/**
 * ChmRasterLayer — fetches and renders a single CHM GeoTIFF tile on the
 * map this component is mounted inside (must be a descendant of
 * <MapContainer>, same as the rest of this dashboard's map layers).
 * Renders nothing itself; manages the raster layer as a side effect.
 */
export function ChmRasterLayer({ s3Key, opacity = 0.8, onError, onBoundsReady }: ChmRasterLayerProps) {
  const map = useMap();
  const layerRef = useRef<L.Layer | null>(null);
  const [loadState, setLoadState] = useState<"idle" | "loading" | "loaded" | "error">("idle");

  useEffect(() => {
    let cancelled = false;
    setLoadState("loading");

    async function addLayer() {
      try {
        const res = await axios.get(`${DATA_BASE_URL}/${s3Key}`, {
          responseType: "arraybuffer",
        });
        if (cancelled) return;

        const georaster = await parseGeoraster(res.data);

        const layer = new GeoRasterLayer({
          georaster,
          opacity,
          resolution: 128,
          pixelValuesToColorFn: (values: number[]) => {
            const v = values[0];
            if (v === undefined || v === null || Number.isNaN(v) || v < MIN_CANOPY_HEIGHT_M) {
              return null; // transparent -- below canopy threshold or nodata
            }
            return heightToColor(v);
          },
        });

        layer.addTo(map);
        layerRef.current = layer;
        const bounds = layer.getBounds();
        onBoundsReady?.(bounds);
        setLoadState("loaded");
      } catch (e) {
        const message = e instanceof Error ? e.message : String(e);
        setLoadState("error");
        onError?.(message);
        console.error("[ChmRasterLayer] failed to load", s3Key, message);
      }
    }

    addLayer();
    return () => {
      cancelled = true;
      if (layerRef.current) {
        map.removeLayer(layerRef.current);
        layerRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [s3Key]);

  // Same pattern as the rest of the dashboard: no visible React output,
  // the map layer itself is the "render". loadState is exposed via
  // onError/onBoundsReady callbacks for the parent to surface in its own UI.
  void loadState;
  return null;
}
