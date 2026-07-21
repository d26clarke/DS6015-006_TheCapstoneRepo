// ─── lidarData.ts ────────────────────────────────────────────────────────────
// Loads canopy_cover.csv and centroids.csv for a county, transparently
// merging across sharded parallel-job output (part_aa, part_ab, ... part_aj)
// when present, or falling back to the unsharded path for counties run as
// a single job.
//
// This exists because, per the pipeline's current architecture, sharded
// counties don't get a single merged output file server-side -- each part's
// run writes its own {county}_canopy_cover.csv / {county}_centroids.csv
// under its own part_XX/ subfolder. Rather than requiring a separate Python
// merge step before the dashboard can show county-wide totals, this loader
// does the merge client-side: try all ten possible part suffixes plus the
// unsharded path, and concatenate whatever actually exists (404s are
// expected and silently skipped).

import axios from "axios";
import Papa from "papaparse";
import DATA_BASE_URL from "./config";

export interface CoverRow {
  tile_id: string;
  project_year: string;
  canopy_cover_firstreturn: number;
  canopy_cover_raster: number;
  n_trees: number;
  veg_source: "classified" | "derived_hag" | "n/a" | string;
  /** Which shard this row came from (e.g. "part_aa"), or "" for an
   *  unsharded county. Needed to build correct per-tile S3 keys for
   *  geotiff/canopy_mask lookups, since sharded counties nest those
   *  under a part_XX/ prefix that isn't part of tile_id itself. */
  _part: string;
}

export interface CentroidRow {
  tile_id: string;
  project_year: string;
  easting_m: number;
  northing_m: number;
  height_m: number;
  _part: string;
}

// Matches the pipeline's actual sharding scheme (see run_parallel's
// part_([a-z]+) regex) -- aa through aj, ten parts.
const PART_SUFFIXES = ["aa", "ab", "ac", "ad", "ae", "af", "ag", "ah", "ai", "aj"];

async function fetchCsv<T>(url: string): Promise<T[] | null> {
  try {
    const res = await axios.get<string>(url, { responseType: "text" });
    const parsed = Papa.parse<T>(res.data, {
      header: true,
      dynamicTyping: true,
      skipEmptyLines: true,
    });
    return parsed.data;
  } catch {
    // 404 (part doesn't exist) or any other fetch failure -- treat as
    // "this shard isn't present", not a hard error, since we don't know
    // ahead of time how many parts a given county was split into.
    return null;
  }
}

/**
 * Fetch and merge a county's canopy cover data across all existing shards.
 * Tries part_aa.../part_aj first, then the unsharded path, and concatenates
 * whatever responds successfully.
 */
export async function loadCountyCoverData(county: string): Promise<CoverRow[]> {
  const base = `${DATA_BASE_URL}/lidar/${county}`;

  const partResults = await Promise.all(
    PART_SUFFIXES.map(async (suffix) => {
      const rows = await fetchCsv<CoverRow>(`${base}/part_${suffix}/${county}_canopy_cover.csv`);
      return rows?.map((r) => ({ ...r, _part: `part_${suffix}` })) ?? null;
    })
  );
  const unshardedRows = await fetchCsv<CoverRow>(`${base}/${county}_canopy_cover.csv`);
  const unsharded = unshardedRows?.map((r) => ({ ...r, _part: "" })) ?? null;

  const allRows = [...partResults, unsharded]
    .filter((rows): rows is CoverRow[] => rows !== null)
    .flat();

  if (allRows.length === 0) {
    throw new Error(
      `No canopy cover data found for ${county} (checked ${PART_SUFFIXES.length} ` +
        `sharded parts plus the unsharded path)`
    );
  }
  return allRows;
}

/**
 * Fetch and merge a county's tree centroid data across all existing shards.
 * Same merge strategy as loadCountyCoverData. Note centroid files can be
 * very large (hundreds of MB, millions of rows for a full county) --
 * callers should expect this to take a while and should not render every
 * row directly (see TreeCentroidsLayer.tsx for the viewport-limited
 * rendering approach this is meant to feed).
 */
export async function loadCountyCentroidData(county: string): Promise<CentroidRow[]> {
  const base = `${DATA_BASE_URL}/lidar/${county}`;

  const partResults = await Promise.all(
    PART_SUFFIXES.map(async (suffix) => {
      const rows = await fetchCsv<CentroidRow>(`${base}/part_${suffix}/${county}_centroids.csv`);
      return rows?.map((r) => ({ ...r, _part: `part_${suffix}` })) ?? null;
    })
  );
  const unshardedRows = await fetchCsv<CentroidRow>(`${base}/${county}_centroids.csv`);
  const unsharded = unshardedRows?.map((r) => ({ ...r, _part: "" })) ?? null;

  const allRows = [...partResults, unsharded]
    .filter((rows): rows is CentroidRow[] => rows !== null)
    .flat();

  return allRows; // empty array is valid here (e.g. while centroids haven't loaded yet)
}
