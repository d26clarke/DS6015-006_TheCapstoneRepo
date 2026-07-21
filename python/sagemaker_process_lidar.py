"""
sagemaker_process_lidar.py — SageMaker VGIN LiDAR LAZ Processing Pipeline
======================================================================
Adapted for AWS SageMaker Processing Jobs. 

County and year are derived automatically from the SM_INPUT_CSV_S3 environment
variable injected by the launcher (e.g.
  s3://central-virginia-tree-canopy-project/data/outputs/Albemarle/CentralVA_LiDAR_Albemarle.csv
  → county = "Albemarle"
  → year   = parsed from the CSV "Year" column, or "unknown" if absent)

Outputs written to /opt/ml/processing/output/<County>/ (auto-uploaded to S3):
  geotiff/               — CHM GeoTIFFs, one per tile
  canopy_mask/           — Binary canopy mask GeoTIFFs, one per tile
  centroids_raw/         — Per-tile tree crown centroid CSVs
  <County>_<year>_centroids.csv       — Combined master centroid file
  <County>_<year>_canopy_cover.csv    — Per-tile canopy cover fractions
  logs/                  — Run summary and skipped-tile audit log

Canopy cover is computed using two complementary methods per tile:
  1. First-return ratio  — (veg first returns ≥ 2 m) / (total first returns)
                           Standard method; directly comparable to GEDI cover fraction.
  2. CHM cell fraction   — (CHM cells ≥ 2 m) / (total raster cells)
                           Spatial method; suitable for dashboard raster layers.

Usage inside SageMaker (no --county or --year needed):
  python sagemaker_process_lidar.py \
      --csv /opt/ml/processing/input/CentralVA_LiDAR_Albemarle.csv \
      --workers 14
"""

import argparse
import csv
import io
import logging
import multiprocessing
import os
import re
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import List, Tuple

import laspy
import numpy as np
import requests
import rasterio
from rasterio.transform import from_origin
from scipy.interpolate import griddata
from scipy.ndimage import maximum_filter

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(iterable, **kwargs):
        return iterable

# Configuration Constants
FT_TO_M             = 0.3048006096
OUTPUT_CRS          = "EPSG:6591"
MIN_CANOPY_HEIGHT_M = 2.0
MAX_CANOPY_HEIGHT_M = 60.0
CROWN_RADIUS_M      = 3.0
RASTER_RESOLUTION   = 1.0
DEFAULT_WORKERS     = max(1, os.cpu_count() - 2)

SM_INPUT_DIR  = Path("/opt/ml/processing/input")
SM_OUTPUT_DIR = Path("/opt/ml/processing/output")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [PID %(process)d] %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 0 — Derive county and year from environment / CSV
# ══════════════════════════════════════════════════════════════════════════════

def derive_county_from_env() -> str:
    """
    Parse the county name from the SM_INPUT_CSV_S3 environment variable.

    Expected path format:
      s3://<bucket>/data/outputs/<County>/CentralVA_LiDAR_<County>.csv
    """
    s3_path = os.environ.get("SM_INPUT_CSV_S3", "")
    if s3_path:
        match = re.search(r"/data/outputs/([^/]+)/", s3_path)
        if match:
            return match.group(1)
        filename = s3_path.rstrip("/").split("/")[-1]
        match = re.match(r"CentralVA_LiDAR_(.+)\.csv", filename, re.IGNORECASE)
        if match:
            return match.group(1)
    logger.warning("SM_INPUT_CSV_S3 not set or unparseable — county set to 'unknown'")
    return "unknown"


def derive_year_from_csv(csv_path: str) -> str:
    """
    Read the first data row of the tile CSV and return the value of a
    'Year' / 'YEAR' / 'year' column if present. Returns 'unknown' otherwise.
    """
    try:
        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                year_val = row.get("Year", row.get("YEAR", row.get("year", "")))
                if year_val.strip():
                    return year_val.strip()
    except Exception:
        pass
    return "unknown"


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — CSV Parsing
# ══════════════════════════════════════════════════════════════════════════════

def _extract_url(cell: str) -> str:
    if not cell:
        return ""
    match = re.search(r'href=["\']+(https?://[^"\'> ]+)', cell)
    if match:
        return match.group(1)
    if cell.strip().startswith("http"):
        return cell.strip()
    return ""


def load_tile_list(csv_path: str, county_filter: str = None,
                   current_only: bool = True) -> List[Tuple[str, str]]:
    tiles = []
    skipped_superceded = 0
    skipped_no_url = 0

    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if county_filter:
                county_val = row.get("County", row.get("COUNTY", ""))
                if county_filter.lower() not in county_val.lower():
                    continue

            if current_only:
                comment = row.get("VComment", row.get("VCOMMENT", ""))
                if "replaced" in comment.lower():
                    skipped_superceded += 1
                    continue

            url = _extract_url(row.get("PointClo_2", row.get("POINTCLO_2", "")))
            if not url:
                skipped_no_url += 1
                continue

            tile_id = row.get("TileID", row.get("TILEID", ""))
            geotiff_filename = (f"{tile_id}_chm.tif" if tile_id
                                else Path(url).stem + "_chm.tif")
            tiles.append((url, geotiff_filename))

    logger.info(
        f"Tile list loaded: {len(tiles)} tiles | "
        f"skipped superceded={skipped_superceded} no_url={skipped_no_url}"
    )
    return tiles


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — Thread-Safe Skip Logging
# ══════════════════════════════════════════════════════════════════════════════

_skip_lock = None
_skip_log_path = None


def _init_worker(lock, skip_log_path: str) -> None:
    global _skip_lock, _skip_log_path
    _skip_lock = lock
    _skip_log_path = Path(skip_log_path)


def _log_skipped(url: str, filename: str, reason: str,
                 total_pts: int, ground_pts: int, veg_pts: int) -> None:
    _skip_log_path.parent.mkdir(parents=True, exist_ok=True)
    if _skip_lock:
        _skip_lock.acquire()
    try:
        write_header = not _skip_log_path.exists()
        with open(_skip_log_path, "a", newline="") as f:
            writer = csv.writer(f)
            if write_header:
                writer.writerow([
                    "url", "filename", "reason",
                    "total_points", "ground_points", "veg_points",
                ])
            writer.writerow([url, filename, reason, total_pts, ground_pts, veg_pts])
    finally:
        if _skip_lock:
            _skip_lock.release()


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — Core Processing Function
# ══════════════════════════════════════════════════════════════════════════════

def process_file(url: str, geotiff_filename: str,
                 out_dir_geotiff: str, out_dir_centroid: str,
                 out_dir_canopy_mask: str,
                 retries: int = 3, timeout: int = 120) -> dict:
    """
    Download, decompress, and process a single VGIN LAZ tile.

    Pipeline stages: 
      1.  HTTP download (chunked streaming)
      2.  LAZ decompression via laspy + Laszip backend
      3.  Point classification diagnostics and skip guards
      4.  Canopy cover — first-return ratio method
      5.  Coordinate extraction
      6.  DTM interpolation (ground points → griddata)
      7.  DSM rasterisation (vegetation max-return)
      8.  CHM computation (DSM − DTM) with height thresholds
      9.  Canopy cover — CHM cell fraction method
      10. Binary canopy mask GeoTIFF write 
      11. Local maxima detection → tree canopy centroids
      12. CHM GeoTIFF write
      13. Centroid CSV write

    Returns a result dict with keys:
      status                    : "success" | "skipped" | "failed"
      filename                  : geotiff_filename
      url                       : source URL
      n_trees                   : number of tree crowns detected
      canopy_cover_firstreturn  : first-return ratio cover fraction
      canopy_cover_raster       : CHM cell fraction cover  
      skip_reason               : reason string if status == "skipped"
      elapsed_s                 : total wall-clock seconds
    """
    pid = os.getpid()
    result = {
        "status":                   "failed",
        "filename":                 geotiff_filename,
        "url":                      url,
        "n_trees":                  0,
        "canopy_cover_firstreturn": None,
        "canopy_cover_raster":      None,
        "skip_reason":              "",
        "elapsed_s":                0.0,
    }

    geotiff_path      = Path(out_dir_geotiff)      / geotiff_filename
    centroid_path     = Path(out_dir_centroid)     / geotiff_filename.replace("_chm.tif", "_centroids.csv")
    canopy_mask_path  = Path(out_dir_canopy_mask)  / geotiff_filename.replace("_chm.tif", "_canopy_mask.tif")
    t_attempt_start   = time.perf_counter()

    for attempt in range(1, retries + 1):
        try:
            # Stage 1: HTTP Download 
            logger.info(f"[{pid}] GET {url}")
            response = requests.get(url, stream=True, timeout=timeout)
            response.raise_for_status()
            buffer = io.BytesIO()
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                buffer.write(chunk)
            buffer.seek(0)
            file_size_mb = buffer.tell() / 1e6
            logger.info(f"[{pid}] Downloaded {file_size_mb:.1f} MB")

            # Stage 2: LAZ Decompression
            with laspy.open(buffer, laz_backend=laspy.LazBackend.Laszip) as fh:
                las = fh.read()

            total_pts = len(las.points)
            if total_pts == 0:
                _log_skipped(url, geotiff_filename, "empty_file", 0, 0, 0)
                result.update(status="skipped", skip_reason="empty_file",
                               elapsed_s=time.perf_counter() - t_attempt_start)
                return result

            # Stage 3: Classification Diagnostics
            classes     = las.classification
            ground_mask = (classes == 2)
            veg_mask    = (classes == 3) | (classes == 4) | (classes == 5)
            ground_pts  = int(np.count_nonzero(ground_mask))
            veg_pts     = int(np.count_nonzero(veg_mask))

            if ground_pts < 10:
                _log_skipped(url, geotiff_filename, "no_ground",
                             total_pts, ground_pts, veg_pts)
                result.update(status="skipped", skip_reason="no_ground",
                               elapsed_s=time.perf_counter() - t_attempt_start)
                return result

            if veg_pts < 10:
                _log_skipped(url, geotiff_filename, "no_vegetation",
                             total_pts, ground_pts, veg_pts)
                result.update(status="skipped", skip_reason="no_vegetation",
                               elapsed_s=time.perf_counter() - t_attempt_start)
                return result

            # Stage 4: Canopy Cover — First-Return Ratio Method
            # Standard method used by USFS FIA and directly comparable to
            # GEDI canopy cover fraction.
            #
            # Formula:
            #   cover = (first returns classified as vegetation) /
            #           (all first returns)
            #
            # Note: return_number == 1 identifies the first (highest) return
            # of each laser pulse — the return that hits the top of the canopy
            # before penetrating to lower surfaces or the ground.
            first_return_mask   = (las.return_number == 1)
            first_returns_total = int(np.count_nonzero(first_return_mask))

            if first_returns_total > 0:
                veg_first_mask      = first_return_mask & veg_mask
                canopy_first_returns = int(np.count_nonzero(veg_first_mask))
                canopy_cover_fr     = round(canopy_first_returns / first_returns_total, 4)
            else:
                canopy_cover_fr = 0.0

            logger.info(
                f"[{pid}] First-return cover: {canopy_cover_fr:.1%}  "
                f"({canopy_first_returns if first_returns_total > 0 else 0}"
                f"/{first_returns_total} first returns)"
            )

            # Stage 5: Coordinate Extraction
            x_veg = las.x[veg_mask];   y_veg = las.y[veg_mask];   z_veg = las.z[veg_mask]
            x_gnd = las.x[ground_mask]; y_gnd = las.y[ground_mask]; z_gnd = las.z[ground_mask]

            x_min, x_max = float(np.min(las.x)), float(np.max(las.x))
            y_min, y_max = float(np.min(las.y)), float(np.max(las.y))
            cols = max(1, int(np.ceil((x_max - x_min) / RASTER_RESOLUTION)))
            rows = max(1, int(np.ceil((y_max - y_min) / RASTER_RESOLUTION)))

            grid_x, grid_y = np.meshgrid(
                np.linspace(x_min, x_max, cols),
                np.linspace(y_max, y_min, rows),
            )

            # Stage 6: DTM Interpolation
            t0  = time.perf_counter()
            dtm = griddata((x_gnd, y_gnd), z_gnd, (grid_x, grid_y), method="linear")
            logger.info(f"[{pid}] DTM interpolated in {time.perf_counter()-t0:.1f}s")

            # Stage 7: DSM Rasterisation
            veg_col = np.clip(((x_veg - x_min) / RASTER_RESOLUTION).astype(int), 0, cols - 1)
            veg_row = np.clip(((y_max - y_veg) / RASTER_RESOLUTION).astype(int), 0, rows - 1)
            dsm = np.full((rows, cols), np.nan)
            np.maximum.at(dsm, (veg_row, veg_col), z_veg)

            # Stage 8: CHM Computation
            chm = dsm - dtm
            chm[(chm < MIN_CANOPY_HEIGHT_M) | (chm > MAX_CANOPY_HEIGHT_M) | np.isnan(chm)] = 0.0

            # Stage 9: Canopy Cover — CHM Cell Fraction Method
            # Counts raster cells where CHM ≥ MIN_CANOPY_HEIGHT_M.
            # Suitable for spatial mapping and dashboard raster layers.
            total_cells        = rows * cols
            canopy_mask_arr    = (chm >= MIN_CANOPY_HEIGHT_M).astype(np.uint8)
            canopy_cells       = int(np.count_nonzero(canopy_mask_arr))
            canopy_cover_raster = round(canopy_cells / total_cells, 4) if total_cells > 0 else 0.0

            logger.info(
                f"[{pid}] CHM cell cover: {canopy_cover_raster:.1%}  "
                f"({canopy_cells}/{total_cells} cells)"
            )

            # Stage 10: Binary Canopy Mask GeoTIFF Write
            # 1 = canopy (≥ 2 m), 0 = non-canopy
            Path(out_dir_canopy_mask).mkdir(parents=True, exist_ok=True)
            transform = from_origin(x_min, y_max, RASTER_RESOLUTION, RASTER_RESOLUTION)
            with rasterio.open(
                canopy_mask_path, "w", driver="GTiff",
                height=rows, width=cols, count=1, dtype="uint8",
                crs=OUTPUT_CRS, transform=transform, compress="lzw",
            ) as dst:
                dst.write(canopy_mask_arr, 1)

            # Stage 11: Local Maxima → Tree Crown Centroids
            t0 = time.perf_counter()
            neighborhood = max(3, int(np.ceil((CROWN_RADIUS_M * 2) / RASTER_RESOLUTION)))
            local_max    = maximum_filter(chm, size=neighborhood)
            peaks        = (chm == local_max) & (chm > 0)
            peak_rows, peak_cols = np.where(peaks)
            n_trees = len(peak_rows)
            logger.info(f"[{pid}] Crown detection: {n_trees} trees in {time.perf_counter()-t0:.1f}s")

            # Stage 12: CHM GeoTIFF Write
            Path(out_dir_geotiff).mkdir(parents=True, exist_ok=True)
            with rasterio.open(
                geotiff_path, "w", driver="GTiff",
                height=rows, width=cols, count=1, dtype=str(chm.dtype),
                crs=OUTPUT_CRS, transform=transform, compress="lzw",
            ) as dst:
                dst.write(chm, 1)

            # Stage 13: Centroid CSV Write
            Path(out_dir_centroid).mkdir(parents=True, exist_ok=True)
            with open(centroid_path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["easting_m", "northing_m", "height_m"])
                for r, c in zip(peak_rows, peak_cols):
                    writer.writerow([
                        x_min + c * RASTER_RESOLUTION,
                        y_max - r * RASTER_RESOLUTION,
                        round(float(chm[r, c]), 3),
                    ])

            result.update(
                status="success",
                n_trees=n_trees,
                canopy_cover_firstreturn=canopy_cover_fr,
                canopy_cover_raster=canopy_cover_raster,
                elapsed_s=time.perf_counter() - t_attempt_start,
            )
            logger.info(
                f"[{pid}] DONE {geotiff_filename} | "
                f"trees={n_trees} | "
                f"cover_fr={canopy_cover_fr:.1%} | "
                f"cover_chm={canopy_cover_raster:.1%} | "
                f"elapsed={result['elapsed_s']:.1f}s"
            )
            return result

        except Exception as e:
            logger.warning(f"[{pid}] Attempt {attempt}/{retries} error: {e}", exc_info=True)
            if attempt < retries:
                time.sleep(5 * attempt)

    result["elapsed_s"] = time.perf_counter() - t_attempt_start
    logger.error(f"[{pid}] FAIL giving up: {url}")
    return result


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — Parallel Orchestrator
# ══════════════════════════════════════════════════════════════════════════════

def run_parallel(tile_list: List[Tuple[str, str]],
                 max_workers: int, county: str, year: str) -> None:
    t_run_start = time.perf_counter()

    out_dir_base         = SM_OUTPUT_DIR / county
    out_dir_geotiff      = out_dir_base / "geotiff"
    out_dir_centroid     = out_dir_base / "centroids_raw"
    out_dir_canopy_mask  = out_dir_base / "canopy_mask"
    out_dir_logs         = out_dir_base / "logs"

    combined_centroid_path  = out_dir_base / f"{county}_{year}_centroids.csv"
    cover_summary_path      = out_dir_base / f"{county}_{year}_canopy_cover.csv"
    skip_log_path           = out_dir_logs / f"{county}_skipped_tiles.csv"
    run_summary_path        = out_dir_logs / f"{county}_run_summary.txt"

    for d in (out_dir_geotiff, out_dir_centroid, out_dir_canopy_mask, out_dir_logs):
        d.mkdir(parents=True, exist_ok=True)

    manager   = multiprocessing.Manager()
    skip_lock = manager.Lock()
    counters  = {"success": 0, "skipped": 0, "failed": 0, "total_trees": 0}
    all_results = []

    with ProcessPoolExecutor(
        max_workers=max_workers,
        initializer=_init_worker,
        initargs=(skip_lock, str(skip_log_path)),
    ) as executor:
        future_to_tile = {
            executor.submit(
                process_file, url, fname,
                str(out_dir_geotiff),
                str(out_dir_centroid),
                str(out_dir_canopy_mask),
            ): (url, fname)
            for url, fname in tile_list
        }

        for future in tqdm(as_completed(future_to_tile), total=len(tile_list)):
            try:
                res = future.result()
                all_results.append(res)
                counters[res["status"]] += 1
                counters["total_trees"] += res.get("n_trees", 0)
            except Exception as e:
                logger.error(f"Worker failure: {e}")

    # Combine per-tile centroid CSVs into master file
    logger.info("Combining per-tile centroid CSVs into master file...")
    with open(combined_centroid_path, "w", newline="") as master:
        writer = csv.writer(master)
        writer.writerow(["tile_id", "easting_m", "northing_m", "height_m"])
        for centroid_csv in sorted(out_dir_centroid.glob("*_centroids.csv")):
            tile_id = centroid_csv.stem.replace("_centroids", "")
            with open(centroid_csv, newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    writer.writerow([
                        tile_id,
                        row["easting_m"],
                        row["northing_m"],
                        row["height_m"],
                    ])

    # Write per-tile canopy cover summary CSV
    logger.info("Writing canopy cover summary CSV...")
    with open(cover_summary_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "tile_id",
            "canopy_cover_firstreturn",
            "canopy_cover_raster",
            "n_trees",
        ])
        for res in all_results:
            if res["status"] == "success":
                tile_id = res["filename"].replace("_chm.tif", "")
                writer.writerow([
                    tile_id,
                    res.get("canopy_cover_firstreturn", ""),
                    res.get("canopy_cover_raster", ""),
                    res.get("n_trees", 0),
                ])

    # County-level aggregate cover statistics
    fr_values  = [r["canopy_cover_firstreturn"] for r in all_results
                  if r["status"] == "success" and r["canopy_cover_firstreturn"] is not None]
    chm_values = [r["canopy_cover_raster"] for r in all_results
                  if r["status"] == "success" and r["canopy_cover_raster"] is not None]

    county_mean_fr  = sum(fr_values)  / len(fr_values)  if fr_values  else 0.0
    county_mean_chm = sum(chm_values) / len(chm_values) if chm_values else 0.0

    # Run Summary
    t_total = time.perf_counter() - t_run_start
    summary_lines = [
        "=" * 60,
        f"  LIDAR RUN SUMMARY: {county}  (year={year})",
        "=" * 60,
        f"  Total tiles submitted  : {len(tile_list):,}",
        f"  Successful             : {counters['success']:,}",
        f"  Skipped                : {counters['skipped']:,}",
        f"  Failed                 : {counters['failed']:,}",
        f"  Total tree crowns      : {counters['total_trees']:,}",
        f"  Workers                : {max_workers}",
        f"  Wall-clock             : {t_total:.1f}s  ({t_total / 60:.1f} min)",
        "",
        "  CANOPY COVER (county mean across successful tiles)",
        f"  First-return ratio     : {county_mean_fr:.1%}",
        f"  CHM cell fraction      : {county_mean_chm:.1%}",
        "",
        f"  Master centroid CSV    : {combined_centroid_path}",
        f"  Canopy cover CSV       : {cover_summary_path}",
        f"  Skip log               : {skip_log_path}",
        "=" * 60,
    ]
    with open(run_summary_path, "w") as f:
        f.write("\n".join(summary_lines) + "\n")
    for line in summary_lines:
        logger.info(line)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — Entry Point
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="SageMaker VGIN LiDAR processing — county and year derived automatically"
    )
    parser.add_argument(
        "--csv", required=True,
        help="Path to the county-specific tile CSV inside the container "
             "(e.g. /opt/ml/processing/input/CentralVA_LiDAR_Albemarle.csv)"
    )
    parser.add_argument(
        "--workers", type=int, default=DEFAULT_WORKERS,
        help=f"Number of parallel worker processes (default: {DEFAULT_WORKERS})"
    )
    args = parser.parse_args()

    county = derive_county_from_env()
    logger.info(f"Derived county : {county}")

    year = derive_year_from_csv(args.csv)
    logger.info(f"Derived year   : {year}")

    tile_list = load_tile_list(args.csv, current_only=True)

    if not tile_list:
        logger.error(f"No tiles found in {args.csv}. Exiting.")
        sys.exit(1)

    run_parallel(tile_list, args.workers, county, year)
