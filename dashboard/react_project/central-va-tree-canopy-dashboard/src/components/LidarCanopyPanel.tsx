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
  loadCountyCentroidData,
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

/** Builds the geotiff/canopy_mask S3 key for a tile, respecting sharded
 *  counties' part_XX/ prefix (row._part is "" for unsharded counties). */
function tileRasterKey(county: string, row: CoverRow, kind: "geotiff" | "canopy_mask", suffix: string) {
  const partSegment = row._part ? `${row._part}/` : "";
  return `lidar/${county}/${partSegment}${kind}/${row.tile_id}${suffix}`;
}

export default function LidarCanopyPanel() {
  const [county, setCounty] = useState(COUNTIES[0]);
  const [cover, setCover] = useState<CoverRow[]>([]);
  const [centroids, setCentroids] = useState<CentroidRow[]>([]);
  const [selectedTileId, setSelectedTileId] = useState<string | null>(null);
  const [showMask, setShowMask] = useState(false);
  const [showTrees, setShowTrees] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setSelectedTileId(null);
    setCentroids([]);

    loadCountyCoverData(county)
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

    // Centroids can be large (hundreds of MB for a full county) -- load
    // separately so the map/tile picker isn't blocked waiting on them.
    loadCountyCentroidData(county).then((rows) => {
      if (!cancelled) setCentroids(rows);
    });

    return () => {
      cancelled = true;
    };
  }, [county]);

  const selectedRow = useMemo(
    () => cover.find((r) => r.tile_id === selectedTileId) ?? null,
    [cover, selectedTileId]
  );

  const tileCentroids = useMemo(
    () => centroids.filter((c) => c.tile_id === selectedTileId),
    [centroids, selectedTileId]
  );

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
            {showTrees && <TreeCentroidsLayer centroids={tileCentroids} />}
          </MapContainer>
        </div>
      )}

      {!loading && !error && cover.length > 0 && (
        <CountyStatsSummary county={county} cover={cover} />
      )}
    </section>
  );
}
