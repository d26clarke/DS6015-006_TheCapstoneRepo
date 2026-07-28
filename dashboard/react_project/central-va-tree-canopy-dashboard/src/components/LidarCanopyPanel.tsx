// ─── LidarCanopyPanel.tsx ────────────────────────────────────────────────────
// Self-contained section: county + tile selectors, a Leaflet map showing the
// CHM height raster (or binary canopy mask) plus tree crown centroids, and
// county-wide summary stats. Follows the same pattern as the rest of this
// dashboard's sections (SplitPanelDashboard.tsx, AoiTimeSeriesPanel.tsx,
// etc.) -- manages its own state/fetching, gets dropped into App.tsx as a
// single <LidarCanopyPanel /> line, no wiring needed at the App level.

import { useEffect, useMemo, useState } from "react";
import { MapContainer, TileLayer } from "react-leaflet";
import "leaflet/dist/leaflet.css";

import {
  loadCountyCoverData,
  loadTileCentroids,
  type CoverRow,
  type CentroidRow,
} from "../lidarData";
import { ChmRasterLayer } from "./ChmRasterLayer";
import { ChmHeightLegend } from "./ChmHeightLegend";
import { CanopyMaskLayer } from "./CanopyMaskLayer";
import { TreeCentroidsLayer } from "./TreeCentroidsLayer";
import { CountyStatsSummary } from "./CountyStatsSummary";

const COUNTIES = [
  "Albemarle",
  "Augusta",
  "Buckingham",
  "Charlottesville",
  "Fluvanna",
  "Greene",
  "Louisa",
  "Nelson",
  "Rockingham",
];

const TILE_CAP_OPTIONS = [10, 20, 30] as const;
const DEFAULT_TILE_CAP: number = TILE_CAP_OPTIONS[1]; // 20

/** Builds the geotiff/canopy_mask S3 key for a tile, respecting sharded
 *  counties' part_XX/ prefix (row._part is "" for unsharded counties). */
function tileRasterKey(county: string, row: CoverRow, kind: "geotiff" | "canopy_mask", suffix: string) {
  const partSegment = row._part ? `${row._part}/` : "";
  return `lidar/${county}/${partSegment}${kind}/${row.tile_id}${suffix}`;
}

export default function LidarCanopyPanel() {
  const [county, setCounty] = useState(COUNTIES[0]);
  const [tileCap, setTileCap] = useState<number>(DEFAULT_TILE_CAP);
  const [cover, setCover] = useState<CoverRow[]>([]);
  const [centroids, setCentroids] = useState<CentroidRow[]>([]);
  const [selectedTileId, setSelectedTileId] = useState<string | null>(null);
  const [showMask, setShowMask] = useState(false);
  const [showTrees, setShowTrees] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Load cover data for this county, capped to tileCap tiles -- for large
  // counties (some have 1000+ tiles across all shards), this keeps the
  // dropdown small and, since fetching stops once enough tiles are found,
  // avoids ever downloading parts beyond what's actually needed.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setSelectedTileId(null);
    setCentroids([]);

    loadCountyCoverData(county, tileCap)
      .then((rows) => {
        if (cancelled) return;
        setCover(rows);
        if (rows.length) setSelectedTileId(rows[0].tile_id);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [county, tileCap]);

  const selectedRow = useMemo(
    () => cover.find((r) => r.tile_id === selectedTileId) ?? null,
    [cover, selectedTileId]
  );

  // Centroids are loaded per-tile, on demand, from centroids_raw/ -- NOT the
  // county-wide merged file, which is confirmed to be tens of millions of
  // rows (multiple GB) for some counties and would hang a browser tab.
  useEffect(() => {
    let cancelled = false;
    if (!selectedRow) {
      setCentroids([]);
      return;
    }
    loadTileCentroids(county, selectedRow.tile_id, selectedRow._part).then((rows) => {
      if (!cancelled) setCentroids(rows);
    });
    return () => {
      cancelled = true;
    };
  }, [county, selectedRow]);

  return (
    <section style={{ padding: "1.5rem 2rem", fontFamily: "sans-serif" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "1rem" }}>
        <h2 style={{ color: "#1b4332", margin: 0 }}>LiDAR Canopy Height &amp; Cover</h2>

        <div style={{ display: "flex", gap: "1rem", alignItems: "center", fontSize: "0.85rem" }}>
          <label>
            County:{" "}
            <select
              value={county}
              onChange={(e) => setCounty(e.target.value)}
              style={{ padding: "0.3rem 0.5rem", borderRadius: "4px", border: "1px solid #ccc" }}
            >
              {COUNTIES.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </label>

          <label>
            Max tiles:{" "}
            <select
              value={tileCap}
              onChange={(e) => setTileCap(Number(e.target.value))}
              style={{ padding: "0.3rem 0.5rem", borderRadius: "4px", border: "1px solid #ccc" }}
            >
              {TILE_CAP_OPTIONS.map((n) => (
                <option key={n} value={n}>{n}</option>
              ))}
            </select>
          </label>

          {cover.length > 0 && (
            <label>
              Tile:{" "}
              <select
                value={selectedTileId ?? ""}
                onChange={(e) => setSelectedTileId(e.target.value)}
                style={{ padding: "0.3rem 0.5rem", borderRadius: "4px", border: "1px solid #ccc" }}
              >
                {cover.map((r) => (
                  <option key={`${r._part}-${r.tile_id}`} value={r.tile_id}>
                    {r.tile_id}{r._part ? ` (${r._part})` : ""}
                  </option>
                ))}
              </select>
            </label>
          )}

          <label style={{ cursor: "pointer" }}>
            <input type="checkbox" checked={showMask} onChange={(e) => setShowMask(e.target.checked)} />{" "}
            Canopy mask (vs. height)
          </label>
          <label style={{ cursor: "pointer" }}>
            <input type="checkbox" checked={showTrees} onChange={(e) => setShowTrees(e.target.checked)} />{" "}
            Tree crowns
          </label>
        </div>
      </div>

      {loading && <p style={{ color: "#555" }}>Loading {county}…</p>}
      {error && (
        <p style={{ color: "#b02a2a" }}>
          Couldn't load canopy cover data: {error}
        </p>
      )}

      {!loading && !error && (
        <div style={{ position: "relative", height: "520px", borderRadius: "8px", overflow: "hidden", border: "1px solid #b7e4c7" }}>
          <MapContainer center={[38.03, -78.48]} zoom={12} style={{ height: "100%", width: "100%" }}>
            <TileLayer
              attribution='&copy; OpenStreetMap contributors'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            {selectedRow &&
              (showMask ? (
                <CanopyMaskLayer
                  key={`mask-${selectedRow._part}-${selectedRow.tile_id}`}
                  s3Key={tileRasterKey(county, selectedRow, "canopy_mask", "_canopy_mask.tif")}
                />
              ) : (
                <ChmRasterLayer
                  key={`chm-${selectedRow._part}-${selectedRow.tile_id}`}
                  s3Key={tileRasterKey(county, selectedRow, "geotiff", "_chm.tif")}
                />
              ))}
            {!showMask && <ChmHeightLegend />}
            {showTrees && <TreeCentroidsLayer centroids={centroids} />}
          </MapContainer>
        </div>
      )}

      {!loading && !error && cover.length > 0 && (
        <CountyStatsSummary county={county} cover={cover} />
      )}
    </section>
  );
}
