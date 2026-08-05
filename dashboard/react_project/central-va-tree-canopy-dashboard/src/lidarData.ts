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
// part_([a-z]+) regex) -- aa through aj, ten parts is the upper bound any
// county could have used.
const MAX_PARTS = 10;
const PART_SUFFIXES = Array.from({ length: MAX_PARTS }, (_, i) =>
  "a" + String.fromCharCode("a".charCodeAt(0) + i)
); // ["aa", "ab", ..., "aj"]

async function fetchJson<T>(url: string): Promise<T[] | null> {
  try {
    const res = await axios.get<string>(url, { responseType: "text" });

    // Parse manually rather than letting axios auto-parse JSON: a hosting
    // fallback (e.g. CloudFront serving index.html with a 200 status for a
    // path that doesn't exist) would otherwise silently come through as a
    // raw string res.data instead of throwing -- same lesson learned from
    // fetchCsv's tile_id guard, just for a different response shape.
    let parsed: unknown;
    try {
      parsed = JSON.parse(res.data);
    } catch {
      console.warn(
        `[lidarData] ${url} did not parse as JSON -- likely a fallback/error ` +
        `page served with a 200 status rather than a real 404. Treating as ` +
        `"not present" rather than merging in garbage rows.`
      );
      return null;
    }

    if (!Array.isArray(parsed)) {
      console.warn(
        `[lidarData] ${url} parsed as JSON but is not an array (got ${typeof parsed}) ` +
        `-- treating as "not present".`
      );
      return null;
    }

    return parsed as T[];
  } catch {
    // 404 or any other fetch failure -- treat as "not present", same as fetchCsv.
    return null;
  }
}

async function fetchCsv<T>(url: string): Promise<T[] | null> {
  try {
    const res = await axios.get<string>(url, { responseType: "text" });
    const parsed = Papa.parse<T>(res.data, {
      header: true,
      dynamicTyping: true,
      skipEmptyLines: true,
    });

    // Guard against hosting setups that return a 200 with fallback content
    // (e.g. index.html) for a path that doesn't actually exist, instead of a
    // clean 404 -- axios won't throw on that, and Papa.parse will happily
    // "parse" HTML as CSV, producing rows with no real tile_id field (just
    // whatever garbage header row it extracted). Checking that the expected
    // column actually came through catches this before it's merged into
    // real data and shows up as blank/garbled dropdown entries.
    if (!parsed.meta.fields?.includes("tile_id")) {
      console.warn(
        `[lidarData] ${url} did not parse to a table with a "tile_id" column ` +
        `(got fields: ${parsed.meta.fields?.join(", ") ?? "none"}) -- likely a ` +
        `fallback/error page served with a 200 status rather than a real 404. ` +
        `Treating as "not present" rather than merging in garbage rows.`
      );
      return null;
    }

    return parsed.data;
  } catch {
    // 404 (part doesn't exist) or any other fetch failure -- treat as
    // "this shard isn't present", not a hard error, since we don't know
    // ahead of time how many parts a given county was split into.
    return null;
  }
}

/**
 * Fetch a county's sharded parts, stopping at the first missing part rather
 * than always checking all MAX_PARTS suffixes.
 *
 * Parts are assigned sequentially with no gaps (part_aa, part_ab, part_ac,
 * ... from the pipeline's split -l 500-style sharding), so if part_ac exists
 * but part_ae doesn't, there's no need to also check af through aj -- they
 * can't exist either. This both avoids firing requests that are guaranteed
 * to hit a hosting fallback (CloudFront's SPA 200-instead-of-404 behavior)
 * and avoids the corresponding console warning noise for counties that only
 * used a handful of shards, without hardcoding a per-county part count
 * anywhere -- it just adapts automatically based on what's actually there.
 */
async function fetchShardedParts<T extends { _part: string }>(
  base: string,
  filename: string,
  maxRows?: number
): Promise<T[]> {
  const results: T[] = [];
  for (const suffix of PART_SUFFIXES) {
    const rows = await fetchCsv<Omit<T, "_part">>(`${base}/part_${suffix}/${filename}`);
    if (rows === null) break; // first gap -- no later part can exist either
    const part = `part_${suffix}`;
    results.push(...(rows.map((r) => ({ ...r, _part: part })) as T[]));
    if (maxRows !== undefined && results.length >= maxRows) break; // enough already -- stop fetching further parts
  }
  return maxRows !== undefined ? results.slice(0, maxRows) : results;
}

/**
 * Fetch and merge a county's canopy cover data across all existing shards.
 * Tries part_aa.../part_aj first, then the unsharded path, and concatenates
 * whatever responds successfully.
 *
 * @param maxTiles Optional cap on the number of tiles returned. When set,
 *   fetching stops as soon as enough tiles have been collected -- for a
 *   demo/presentation where only a handful of tiles need to be shown,
 *   this avoids ever fetching parts beyond the first one or two, which
 *   also means loadTileCentroids (per-tile, on demand) never needs to
 *   touch the huge multi-million-row merged centroid data at all.
 */
export async function loadCountyCoverData(county: string, maxTiles?: number): Promise<CoverRow[]> {
  const base = `${DATA_BASE_URL}/lidar/${county}`;

  const shardedRows = await fetchShardedParts<CoverRow>(base, `${county}_canopy_cover.csv`, maxTiles);
  const unshardedRows = await fetchCsv<Omit<CoverRow, "_part">>(`${base}/${county}_canopy_cover.csv`);
  const unsharded = unshardedRows?.map((r) => ({ ...r, _part: "" })) ?? [];

  let allRows = [...shardedRows, ...unsharded];
  if (maxTiles !== undefined) {
    allRows = allRows.slice(0, maxTiles);
  }

  if (allRows.length === 0) {
    throw new Error(
      `No canopy cover data found for ${county} (checked sharded parts up to the ` +
        `first gap, plus the unsharded path)`
    );
  }
  return allRows;
}

/**
 * Fetch and merge a county's tree centroid data across all existing shards.
 * Same merge strategy as loadCountyCoverData.
 *
 * WARNING: this pulls the entire county-wide merged centroid data --
 * confirmed against real production data to be tens of millions of rows
 * (e.g. Albemarle: ~31M, Louisa: ~39M) per county, almost certainly
 * multiple gigabytes as CSV. That's too large to fetch/parse in a browser
 * tab. Prefer loadTileCentroids() below, which fetches only one tile's
 * centroids on demand, unless you specifically need county-wide totals
 * for something other than per-tile map display.
 */
export async function loadCountyCentroidData(county: string): Promise<CentroidRow[]> {
  const base = `${DATA_BASE_URL}/lidar/${county}`;

  const shardedRows = await fetchShardedParts<CentroidRow>(base, `${county}_centroids.csv`);
  const unshardedRows = await fetchCsv<Omit<CentroidRow, "_part">>(`${base}/${county}_centroids.csv`);
  const unsharded = unshardedRows?.map((r) => ({ ...r, _part: "" })) ?? [];

  return [...shardedRows, ...unsharded]; // empty array is valid here (e.g. while centroids haven't loaded yet)
}

/**
 * Fetch centroids for a SINGLE tile, from the per-tile centroids_raw/
 * folder rather than the huge merged county-wide centroids.csv. This is
 * the recommended way to get centroid data for map display -- each
 * per-tile file is small (tens to hundreds of KB) regardless of how many
 * total tiles a county has, since you're only ever fetching the one tile
 * currently selected rather than the entire county's combined data.
 *
 * Tries the JSON version first (immune to the CloudFront-fallback-parsed-
 * as-CSV problem, since JSON.parse throws hard on non-JSON content where a
 * forgiving CSV parser would not), falling back to CSV automatically for
 * counties not yet converted by convert_centroids_to_json.py. No further
 * code change is needed as more counties get converted -- each one starts
 * using JSON the moment its .json file exists in S3.
 *
 * @param part The tile's shard (e.g. "part_aa"), or "" for an unsharded
 *   county -- same value as CoverRow._part for this tile.
 */
export async function loadTileCentroids(
  county: string,
  tileId: string,
  part: string
): Promise<CentroidRow[]> {
  const base = `${DATA_BASE_URL}/lidar/${county}`;
  const partSegment = part ? `${part}/` : "";
  const pathBase = `${base}/${partSegment}centroids_raw/${tileId}_centroids`;

  const jsonRows = await fetchJson<Omit<CentroidRow, "_part">>(`${pathBase}.json`);
  if (jsonRows !== null) {
    return jsonRows.map((r) => ({ ...r, _part: part }));
  }

  const csvRows = await fetchCsv<Omit<CentroidRow, "_part">>(`${pathBase}.csv`);
  return csvRows?.map((r) => ({ ...r, _part: part })) ?? [];
}