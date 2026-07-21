// TreeCentroidsLayer.tsx 
//
// Renders detected tree crown centroids (from *_centroids.csv) on the map.
//
// IMPORTANT performance note: a single county can have 10+ million detected
// trees (Albemarle alone reported ~10.6M crowns in one run). Rendering that
// many individual Leaflet markers -- even with the canvas renderer -- would
// freeze the browser. This component instead:
//   1. Reprojects centroids to WGS84 lazily, only for points inside the
//      current map viewport (recomputed on moveend/zoomend).
//   2. Caps the number of rendered points; above the cap, it shows a
//      "zoom in to see individual trees" message instead of rendering.
//   3. Uses Leaflet's canvas renderer (not SVG/DOM) for the markers it does
//      render, which is substantially faster for point-heavy layers.
//
// For a true county-wide "tree density" view (rather than individual trees),
// pair this with a separate grid-aggregated heatmap layer -- ask if you want
// that built too; it would reuse the same underlying centroid data but bin
// it into cells rather than rendering points directly.

import { useEffect, useMemo, useState } from "react";
import type React from "react";
import { CircleMarker, Popup, useMap, useMapEvents } from "react-leaflet";
import L from "leaflet";
import proj4 from "proj4";
import { heightToColor, CHM_SOURCE_CRS_EPSG } from "./ChmRasterLayer";
import type { CentroidRow } from "../lidarData";

const RENDER_CAP = 4000;

interface TreeCentroidsLayerProps {
  centroids: CentroidRow[];
  maxHeight?: number;
}

export function TreeCentroidsLayer({ centroids, maxHeight = 60 }: TreeCentroidsLayerProps) {
  const map = useMap();
  const [bounds, setBounds] = useState<L.LatLngBounds>(map.getBounds());

  useMapEvents({
    moveend: () => setBounds(map.getBounds()),
    zoomend: () => setBounds(map.getBounds()),
  });

  useEffect(() => {
    setBounds(map.getBounds());
  }, [map]);

  // Reproject once per centroid *only when candidates are being evaluated*,
  // not up front for the whole (potentially millions-strong) dataset.
  const { visible, totalInBounds } = useMemo(() => {
    const candidates: Array<{ row: CentroidRow; lat: number; lon: number }> = [];

    // Cheap pre-filter in source CRS units before paying for a proj4 call
    // per point: convert the current viewport bounds to the source CRS once,
    // then only reproject points whose raw easting/northing plausibly fall
    // inside that box.
    const sw = proj4("WGS84", CHM_SOURCE_CRS_EPSG, [bounds.getWest(), bounds.getSouth()]);
    const ne = proj4("WGS84", CHM_SOURCE_CRS_EPSG, [bounds.getEast(), bounds.getNorth()]);
    const [minX, maxX] = [Math.min(sw[0], ne[0]), Math.max(sw[0], ne[0])];
    const [minY, maxY] = [Math.min(sw[1], ne[1]), Math.max(sw[1], ne[1])];

    for (const row of centroids) {
      if (row.easting_m < minX || row.easting_m > maxX) continue;
      if (row.northing_m < minY || row.northing_m > maxY) continue;
      candidates.push({ row, lat: 0, lon: 0 }); // reprojected lazily below
    }

    const totalInBounds = candidates.length;
    const sample =
      totalInBounds > RENDER_CAP
        ? candidates.filter((_, i) => i % Math.ceil(totalInBounds / RENDER_CAP) === 0)
        : candidates;

    const visible = sample.map(({ row }) => {
      const [lon, lat] = proj4(CHM_SOURCE_CRS_EPSG, "WGS84", [row.easting_m, row.northing_m]);
      return { row, lat, lon };
    });

    return { visible, totalInBounds };
  }, [centroids, bounds]);

  return (
    <>
      {visible.map(({ row, lat, lon }, i) => (
        <CircleMarker
          key={i}
          center={[lat, lon]}
          radius={3}
          renderer={canvasRenderer}
          pathOptions={{
            color: heightToColor(row.height_m, maxHeight),
            fillColor: heightToColor(row.height_m, maxHeight),
            fillOpacity: 0.85,
            weight: 1,
          }}
        >
          <Popup>
            <strong>{row.tile_id}</strong>
            <br />
            Height: {row.height_m.toFixed(1)} m
            <br />
            Year: {row.project_year}
          </Popup>
        </CircleMarker>
      ))}
      {totalInBounds > RENDER_CAP && (
        <div className="tree-centroids-overflow-notice" style={overflowNoticeStyle}>
          Showing a {RENDER_CAP.toLocaleString()}-point sample of{" "}
          {totalInBounds.toLocaleString()} trees in view — zoom in for full detail.
        </div>
      )}
    </>
  );
}

const canvasRenderer = L.canvas({ padding: 0.5 });

const overflowNoticeStyle: React.CSSProperties = {
  position: "absolute",
  bottom: "0.75rem",
  left: "50%",
  transform: "translateX(-50%)",
  zIndex: 1000,
  background: "rgba(27, 67, 50, 0.92)",
  color: "#d8f3dc",
  padding: "0.4rem 0.8rem",
  borderRadius: "6px",
  fontSize: "12px",
  fontFamily: "sans-serif",
  pointerEvents: "none",
  whiteSpace: "nowrap",
};
