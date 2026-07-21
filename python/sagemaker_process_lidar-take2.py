"""
sagemaker_process_lidar.py — SageMaker VGIN LiDAR LAZ Processing Pipeline
======================================================================
Adapted for AWS SageMaker Processing Jobs.

County and year are derived automatically from the SM_INPUT_CSV_S3 environment
variable injected by the launcher (e.g.
  s3://central-virginia-tree-canopy-project/data/inputs/Albemarle/CentralVA_LiDAR_Albemarle.csv
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

Unit handling:
  Each tile's native X/Y/Z linear unit (e.g. US Survey Feet for Virginia
  State Plane South, EPSG:6595) is detected directly from the LAZ file's
  embedded CRS via get_horizontal_unit_to_meters(). All grid math, height
  thresholds, and GeoTIFF output are then performed in true meters so they
  align correctly with OUTPUT_CRS (a meters-based CRS) regardless of the
  source tile's native unit.

Vegetation fallback:
  Some VGIN/USGS 3DEP deliveries (commonly 2015-vintage LPC projects) were
  produced under an earlier Lidar Base Specification whose minimum required
  classification scheme only mandated Ground (2); vegetation classes
  (3/4/5) were an optional add-on some projects never populated, leaving
  all canopy points as Unclassified (1). For such tiles, classification-based
  vegetation detection returns zero points even though vegetation is present.
  compute_vegetation_from_hag() derives a vegetation mask directly from
  height-above-ground for these tiles, so they're processed instead of
  being skipped as "no_vegetation".

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
# SECTION 0A — Unit Detection & HAG-Derived Vegetation Fallback
# ══════════════════════════════════════════════════════════════════════════════

def get_horizontal_unit_to_meters(las) -> float:
    """
    Read the tile's actual horizontal (X/Y) unit conversion factor
    (native unit -> meters) directly from its embedded CRS, rather than
    assuming meters or hardcoding feet.

    For VGIN/USGS tiles in Virginia State Plane South (ftUS), e.g.
    EPSG:6595, this returns 0.30480060960121924 (1 US survey foot in meters).
    Z is assumed to share the same native unit as X/Y, which holds for all
    VGIN Virginia State Plane (ftUS) deliveries observed so far.

    Falls back to the module-level FT_TO_M constant (the VGIN historical
    default) with a warning if no CRS is embedded in the file, since an
    unlabeled tile from this program is far more likely to be in US Survey
    Feet than in meters.
    """
    try:
        crs = las.header.parse_crs()
    except Exception as e:
        logger.warning(f"Could not parse CRS ({e}); assuming native unit is "
                        f"US Survey Feet (FT_TO_M={FT_TO_M})")
        return FT_TO_M

    if crs is None:
        logger.warning("No CRS embedded in file; assuming native unit is "
                        f"US Survey Feet (FT_TO_M={FT_TO_M})")
        return FT_TO_M

    to_meters = crs.axis_info[0].unit_conversion_factor
    unit_name = crs.axis_info[0].unit_name
    logger.info(f"Detected horizontal unit: {unit_name} (1 unit = {to_meters:.10f} m)")
    return to_meters


def compute_vegetation_from_hag(las, to_meters: float, resolution_m: float = RASTER_RESOLUTION,
                                 low_thresh_m: float = 0.15,
                                 med_thresh_m: float = MIN_CANOPY_HEIGHT_M,
                                 high_thresh_m: float = MAX_CANOPY_HEIGHT_M,
                                 candidate_mask: np.ndarray = None) -> dict:
    """
    Derive a vegetation mask from height-above-ground (HAG) using a gridded
    ground surface (DTM) built from Class 2 (Ground) points. Used as a
    fallback when a tile's vendor classification never populated vegetation
    classes 3/4/5 (all canopy points left as Unclassified).

    Parameters
    ----------
    las : laspy LasData
        The already-read point cloud.
    to_meters : float
        Native-unit-to-meters conversion factor, from get_horizontal_unit_to_meters().
    resolution_m : float
        Ground-surface grid cell size in meters.
    low_thresh_m, med_thresh_m, high_thresh_m : float
        Height-above-ground thresholds (meters) separating low/medium/high
        vegetation. med_thresh_m defaults to MIN_CANOPY_HEIGHT_M and
        high_thresh_m to MAX_CANOPY_HEIGHT_M so the derived mask lines up
        with this pipeline's existing canopy height bounds.
    candidate_mask : np.ndarray, optional
        Boolean mask over las.points restricting which points are evaluated
        as vegetation candidates (e.g. classification != 2 to exclude ground).
        Defaults to all non-ground points if not provided.

    Returns
    -------
    dict with keys:
        veg_mask               : boolean array, length == len(candidate points),
                                  True where the point is derived vegetation
        height_above_ground_m  : HAG in meters for each candidate point
        candidate_mask          : the boolean mask (over the full point array)
                                  used to select candidate points
    """
    classification = las.classification
    if candidate_mask is None:
        candidate_mask = (classification != 2)

    ground_mask = (classification == 2)

    # Native-unit coordinates, converted to meters
    gx = las.x[ground_mask] * to_meters
    gy = las.y[ground_mask] * to_meters
    gz = las.z[ground_mask] * to_meters

    cx = las.x[candidate_mask] * to_meters
    cy = las.y[candidate_mask] * to_meters
    cz = las.z[candidate_mask] * to_meters

    empty_result = {
        "veg_mask": np.zeros(cx.shape[0], dtype=bool),
        "height_above_ground_m": np.full(cx.shape[0], np.nan),
        "candidate_mask": candidate_mask,
    }

    if gx.size < 10 or cx.size == 0:
        return empty_result

    x_min, x_max = float(las.x.min()) * to_meters, float(las.x.max()) * to_meters
    y_min, y_max = float(las.y.min()) * to_meters, float(las.y.max()) * to_meters

    ncols = max(1, int(np.ceil((x_max - x_min) / resolution_m)))
    nrows = max(1, int(np.ceil((y_max - y_min) / resolution_m)))

    # Bin ground points into the grid, averaging Z per cell for a coarse DTM
    col_idx = np.clip(((gx - x_min) / resolution_m).astype(int), 0, ncols - 1)
    row_idx = np.clip(((gy - y_min) / resolution_m).astype(int), 0, nrows - 1)

    dtm_sum = np.zeros((nrows, ncols))
    dtm_count = np.zeros((nrows, ncols))
    np.add.at(dtm_sum, (row_idx, col_idx), gz)
    np.add.at(dtm_count, (row_idx, col_idx), 1)

    with np.errstate(invalid="ignore"):
        dtm = dtm_sum / dtm_count
    has_ground = dtm_count > 0

    # Fill grid cells with no ground returns via nearest-neighbor
    filled_rows, filled_cols = np.where(has_ground)
    empty_rows, empty_cols = np.where(~has_ground)
    if empty_rows.size:
        filled_z = dtm[filled_rows, filled_cols]
        dtm[empty_rows, empty_cols] = griddata(
            (filled_rows, filled_cols), filled_z,
            (empty_rows, empty_cols), method="nearest"
        )

    # Look up ground elevation at each candidate point's grid cell
    c_col = np.clip(((cx - x_min) / resolution_m).astype(int), 0, ncols - 1)
    c_row = np.clip(((cy - y_min) / resolution_m).astype(int), 0, nrows - 1)
    ground_z_at_points = dtm[c_row, c_col]

    height_above_ground_m = cz - ground_z_at_points

    low_veg  = (height_above_ground_m > low_thresh_m) & (height_above_ground_m <= med_thresh_m)
    med_veg  = (height_above_ground_m > med_thresh_m) & (height_above_ground_m <= high_thresh_m)
    high_veg = (height_above_ground_m > high_thresh_m)
    veg_mask = low_veg | med_veg | high_veg

    return {
        "veg_mask": veg_mask,
        "height_above_ground_m": height_above_ground_m,
        "candidate_mask": candidate_mask,
    }


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 0 — Derive county and year from environment / CSV
# ══════════════════════════════════════════════════════════════════════════════

def derive_county_from_env() -> str:
    """
    Parse the county name from the SM_INPUT_CSV_S3 environment variable.

    Expected path format:
      s3://<bucket>/data/inputs/<County>/CentralVA_LiDAR_<County>.csv
    """
    s3_path = os.environ.get("SM_INPUT_CSV_S3", "")
    if s3_path:
        match = re.search(r"/data/inputs/([^/]+)/", s3_path)
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
    Read the first data row of the tile CSV and return the LiDAR acquisition year
    from the 'ProjectYea' column (VGIN data dictionary field name).
    Returns 'unknown' if the column is absent or empty.
    """
    try:
        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # VGIN field name is 'ProjectYea' (truncated at 10 chars by shapefile convention)
                year_val = (
                    row.get("ProjectYea") or
                    row.get("PROJECTYEA") or
                    row.get("projectyea") or
                    row.get("Year") or       # fallback for any reformatted exports
                    row.get("YEAR") or
                    ""
                )
                if str(year_val).strip():
                    return str(year_val).strip()
    except Exception:
        pass
    return "unknown"


# def derive_year_from_csv(csv_path: str) -> str:
#     """
#     Read the first data row of the tile CSV and return the value of a
#     'Year' / 'YEAR' / 'year' column if present. Returns 'unknown' otherwise.
#     """
#     try:
#         with open(csv_path, newline="", encoding="utf-8-sig") as f:
#             reader = csv.DictReader(f)
#             for row in reader:
#                 year_val = row.get("Year", row.get("YEAR", row.get("year", "")))
#                 if year_val.strip():
#                     return year_val.strip()
#     except Exception:
#         pass
#     return "unknown"


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — CSV Parsing
# ══════════════════════════════════════════════════════════════════════════════

def _extract_url(cell: str) -> str:
    """
    Extract a plain URL from an ArcGIS HTML anchor cell.
    ArcGIS exports download links as:  <a href=""https://..."">Download LPC</a>
    Returns an empty string if no URL is found.
    """
    if not cell:
        return ""
    # Handle double-double-quote ArcGIS artefact: href=""https://...""
    match = re.search(r'href=["\']+(https?://[^"\'> ]+)', cell)
    if match:
        return match.group(1)
    # Plain URL (no HTML wrapper)
    if cell.strip().startswith("http"):
        return cell.strip()
    return ""

def load_tile_list(csv_path: str, current_only: bool = True) -> List[Tuple[str, str, str]]:
    """
    Returns list of (url, geotiff_filename, project_year) tuples.
    project_year is the per-tile acquisition year from the ProjectYea column.
    """
    tiles = []
    skipped_superseded = 0
    skipped_no_url = 0

    logger.info(
        f"CSV Path: {csv_path} | "
        f"Verify the file exists and is not completely empty (0 bytes) {os.path.exists(csv_path) and os.path.getsize(csv_path)}"
    )

    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if current_only:
                comment = row.get("VComment", row.get("VCOMMENT", ""))
                if "replaced" in comment.lower():
                    skipped_superseded += 1
                    logger.info(
                        f"SKIPPED: Comment contains replaced."
                    )
                    continue

            url = _extract_url(row.get("PointClo_2", row.get("POINTCLO_2", "")))
            if not url:
                skipped_no_url += 1
                logger.info(
                    f"SKIPPED: No URL."
                )
                continue

            tile_id = row.get("TileName", row.get("TILENAME", ""))
            geotiff_filename = (f"{tile_id}_chm.tif" if tile_id
                                else Path(url).stem + "_chm.tif")

            # Capture per-tile acquisition year from ProjectYea
            project_year = str(
                row.get("ProjectYea") or
                row.get("PROJECTYEA") or
                "unknown"
            ).strip()

            tiles.append((url, geotiff_filename, project_year))

    logger.info(
        f"Tile list loaded: {len(tiles)} tiles | "
        f"skipped superseded={skipped_superseded} no_url={skipped_no_url}"
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

def process_file(url: str, geotiff_filename: str, project_year: str,
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
        "project_year":             project_year,
        "canopy_cover_firstreturn": None,
        "canopy_cover_raster":      None,
        "veg_source":               "n/a",
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

            # Stage 2.5: Native Unit Detection
            # Read the tile's actual X/Y/Z unit conversion factor from its
            # embedded CRS rather than assuming meters. VGIN tiles in
            # Virginia State Plane (ftUS) need this scaling applied before
            # any grid math or height threshold comparison downstream.
            to_meters = get_horizontal_unit_to_meters(las)

            # Stage 3: Classification Diagnostics
            classes     = las.classification
            ground_mask = (classes == 2)
            veg_mask    = (classes == 3) | (classes == 4) | (classes == 5)
            ground_pts  = int(np.count_nonzero(ground_mask))
            veg_pts     = int(np.count_nonzero(veg_mask))
            veg_source  = "classified"

            if ground_pts < 10:
                _log_skipped(url, geotiff_filename, "no_ground",
                             total_pts, ground_pts, veg_pts)
                result.update(status="skipped", skip_reason="no_ground",
                               elapsed_s=time.perf_counter() - t_attempt_start)
                return result

            if veg_pts == 0:
                # Classification-based vegetation is absent. This is common for
                # earlier-vintage USGS 3DEP LPC deliveries (e.g. 2015) whose
                # minimum required classification scheme only mandated Ground —
                # vegetation classes 3/4/5 were an optional add-on that some
                # projects never populated, leaving all canopy points as
                # Unclassified (1). Before giving up, derive vegetation from
                # height-above-ground instead of classification.
                logger.info(
                    f"[{pid}] No classified vegetation (classes 3/4/5) found — "
                    f"falling back to height-above-ground derived vegetation"
                )
                hag_result = compute_vegetation_from_hag(las, to_meters=to_meters)
                derived_candidate_mask = hag_result["candidate_mask"]
                derived_veg_local      = hag_result["veg_mask"]

                # Expand the derived (candidate-space) mask back to full point-array space
                veg_mask = np.zeros(total_pts, dtype=bool)
                veg_mask[derived_candidate_mask] = derived_veg_local
                veg_pts = int(np.count_nonzero(veg_mask))
                veg_source = "derived_hag"

                if veg_pts == 0:
                    _log_skipped(url, geotiff_filename, "no_vegetation",
                                 total_pts, ground_pts, veg_pts)
                    result.update(status="skipped", skip_reason="no_vegetation",
                                   elapsed_s=time.perf_counter() - t_attempt_start)
                    return result

                logger.info(
                    f"[{pid}] Derived {veg_pts:,} vegetation point(s) from "
                    f"height-above-ground (threshold: {MIN_CANOPY_HEIGHT_M}-"
                    f"{MAX_CANOPY_HEIGHT_M} m)"
                )

            result["veg_source"] = veg_source

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
            # All coordinates converted to true meters via the detected unit
            # factor (Stage 2.5) before any grid math -- RASTER_RESOLUTION,
            # MIN/MAX_CANOPY_HEIGHT_M, and CROWN_RADIUS_M are all specified
            # in meters and OUTPUT_CRS is a meters-based CRS, so working in
            # native units here (e.g. US Survey Feet) would silently build a
            # ~3.28x-too-fine grid and misalign every GeoTIFF written below.
            x_veg = las.x[veg_mask] * to_meters
            y_veg = las.y[veg_mask] * to_meters
            z_veg = las.z[veg_mask] * to_meters
            x_gnd = las.x[ground_mask] * to_meters
            y_gnd = las.y[ground_mask] * to_meters
            z_gnd = las.z[ground_mask] * to_meters

            x_min, x_max = float(np.min(las.x)) * to_meters, float(np.max(las.x)) * to_meters
            y_min, y_max = float(np.min(las.y)) * to_meters, float(np.max(las.y)) * to_meters
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
                veg_source=veg_source,
                elapsed_s=time.perf_counter() - t_attempt_start,
            )
            logger.info(
                f"[{pid}] DONE {geotiff_filename} | "
                f"trees={n_trees} | "
                f"cover_fr={canopy_cover_fr:.1%} | "
                f"cover_chm={canopy_cover_raster:.1%} | "
                f"veg_source={veg_source} | "
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

def run_parallel(tile_list: List[Tuple[str, str, str]],
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
                process_file, url, fname, project_year,
                str(out_dir_geotiff),
                str(out_dir_centroid),
                str(out_dir_canopy_mask),
            ): (url, fname, project_year)
            for url, fname, project_year in tile_list
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
        writer.writerow(["tile_id", "project_year", "easting_m", "northing_m", "height_m"])
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
            "project_year",
            "canopy_cover_firstreturn",
            "canopy_cover_raster",
            "n_trees",
            "veg_source",
        ])
        for res in all_results:
            if res["status"] == "success":
                tile_id = res["filename"].replace("_chm.tif", "")
                writer.writerow([
                    tile_id,
                    res.get("canopy_cover_firstreturn", ""),
                    res.get("canopy_cover_raster", ""),
                    res.get("n_trees", 0),
                    res.get("veg_source", "n/a"),
                ])

    # County-level aggregate cover statistics
    fr_values  = [r["canopy_cover_firstreturn"] for r in all_results
                  if r["status"] == "success" and r["canopy_cover_firstreturn"] is not None]
    chm_values = [r["canopy_cover_raster"] for r in all_results
                  if r["status"] == "success" and r["canopy_cover_raster"] is not None]

    county_mean_fr  = sum(fr_values)  / len(fr_values)  if fr_values  else 0.0
    county_mean_chm = sum(chm_values) / len(chm_values) if chm_values else 0.0

    from collections import Counter
    
    year_counts = Counter(r["project_year"] for r in all_results if r["status"] == "success")
    year_summary = ", ".join(f"{yr}: {cnt} tiles" for yr, cnt in sorted(year_counts.items()))

    veg_source_counts = Counter(r.get("veg_source", "n/a") for r in all_results if r["status"] == "success")
    veg_source_summary = ", ".join(f"{src}: {cnt} tiles" for src, cnt in sorted(veg_source_counts.items()))

    # Run Summary
    t_total = time.perf_counter() - t_run_start
    summary_lines = [
        "=" * 60,
        f"  Acquisition years: {county}  (years={year_summary})",
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
        f"  Vegetation source      : {veg_source_summary}",
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
        "--county", required=True,
        help="The Selected County"
    )
    parser.add_argument(
        "--workers", type=int, default=DEFAULT_WORKERS,
        help=f"Number of parallel worker processes (default: {DEFAULT_WORKERS})"
    )
    args = parser.parse_args()

    #county = derive_county_from_env()
    county = args.county
    logger.info(f"Derived county : {county}")

    year = derive_year_from_csv(args.csv)
    logger.info(f"Derived year   : {year}")

    tile_list = load_tile_list(args.csv, current_only=True)

    if not tile_list:
        logger.error(f"No tiles found in {args.csv}. Exiting.")
        sys.exit(1)

    run_parallel(tile_list, args.workers, county, year)


