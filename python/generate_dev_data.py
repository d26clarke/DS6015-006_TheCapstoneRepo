"""
generate_dev_data.py

Builds small, realistic local development test data for the Central Virginia
Tree Canopy dashboard -- matching the exact folder structure the deployed
S3 data has, so lidarData.ts / ChmRasterLayer.tsx / CanopyMaskLayer.tsx can
be tested locally against public/data/ without touching the large production
files.

Output layout (drop straight into <project>/public/data/):

  data/lidar/Charlottesville/
      Charlottesville_canopy_cover.csv
      Charlottesville_centroids.csv
      geotiff/S13_4889_10_chm.tif
      geotiff/S13_4889_20_chm.tif
      canopy_mask/S13_4889_10_canopy_mask.tif
      canopy_mask/S13_4889_20_canopy_mask.tif

  data/lidar/Albemarle/part_aa/...   (sharded example, 3 tiles)
  data/lidar/Albemarle/part_ab/...   (sharded example, 3 tiles)

Coordinates use the same placeholder CRS as ChmRasterLayer.tsx's
CHM_SOURCE_CRS_EPSG/CHM_SOURCE_CRS_PROJ4 (Virginia State Plane South,
meters) -- replace both this script's PROJ4 string and the dashboard's if
your real OUTPUT_CRS differs.
"""

import csv
import os
import random

import numpy as np
import rasterio
from rasterio.transform import from_origin

random.seed(42)
np.random.seed(42)

OUT_ROOT = "public_data_test/data/lidar"

# Same placeholder as ChmRasterLayer.tsx -- keep these in sync.
SOURCE_CRS_PROJ4 = (
    "+proj=lcc +lat_1=37.96666666666667 +lat_2=36.76666666666667 "
    "+lat_0=36.33333333333334 +lon_0=-78.5 +x_0=3500000 +y_0=1000000 "
    "+ellps=GRS80 +units=m +no_defs"
)

MIN_CANOPY_HEIGHT_M = 2.0
MAX_CANOPY_HEIGHT_M = 60.0


def make_synthetic_chm(width=300, height=300, seed=0):
    """Smooth, plausible-looking canopy height surface: a few Gaussian
    'tree clusters' over bare ground, values in meters."""
    rng = np.random.default_rng(seed)
    grid = np.zeros((height, width), dtype=np.float32)
    n_clusters = rng.integers(15, 30)
    yy, xx = np.mgrid[0:height, 0:width]
    for _ in range(n_clusters):
        cx, cy = rng.uniform(0, width), rng.uniform(0, height)
        sigma = rng.uniform(8, 25)
        peak = rng.uniform(10, MAX_CANOPY_HEIGHT_M * 0.9)
        grid += peak * np.exp(-(((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * sigma ** 2)))
    grid += rng.normal(0, 0.3, size=grid.shape)  # sensor noise
    grid = np.clip(grid, 0, MAX_CANOPY_HEIGHT_M)
    return grid


def write_geotiff(path, array, x_min, y_max, resolution_m, proj4_str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    transform = from_origin(x_min, y_max, resolution_m, resolution_m)
    with rasterio.open(
        path, "w",
        driver="GTiff",
        height=array.shape[0],
        width=array.shape[1],
        count=1,
        dtype=array.dtype,
        crs=proj4_str,
        transform=transform,
        compress="deflate",
    ) as dst:
        dst.write(array, 1)


def make_centroids_for_tile(tile_id, project_year, x_min, y_max, resolution_m,
                             chm, n_trees=150, seed=0):
    """Sample plausible tree centroids from local maxima of the synthetic CHM
    (not a real local-maxima algorithm -- just enough to look plausible for
    dev testing)."""
    rng = np.random.default_rng(seed)
    rows = []
    height, width = chm.shape
    attempts = 0
    while len(rows) < n_trees and attempts < n_trees * 20:
        attempts += 1
        r, c = rng.integers(0, height), rng.integers(0, width)
        h = float(chm[r, c])
        if h < MIN_CANOPY_HEIGHT_M:
            continue
        easting = x_min + c * resolution_m
        northing = y_max - r * resolution_m
        rows.append({
            "tile_id": tile_id,
            "project_year": project_year,
            "easting_m": round(easting, 3),
            "northing_m": round(northing, 3),
            "height_m": round(h, 3),
        })
    return rows


def write_csv(path, rows, fieldnames):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def make_cover_row(tile_id, project_year, n_trees, veg_source, seed=0):
    rng = np.random.default_rng(seed)
    fr = round(float(rng.uniform(0.25, 0.85)), 4)
    chm_cover = round(min(1.0, fr * float(rng.uniform(1.05, 1.35))), 4)
    return {
        "tile_id": tile_id,
        "project_year": project_year,
        "canopy_cover_firstreturn": fr,
        "canopy_cover_raster": chm_cover,
        "n_trees": n_trees,
        "veg_source": veg_source,
    }


COVER_FIELDS = ["tile_id", "project_year", "canopy_cover_firstreturn",
                "canopy_cover_raster", "n_trees", "veg_source"]
CENTROID_FIELDS = ["tile_id", "project_year", "easting_m", "northing_m", "height_m"]

RESOLUTION_M = 5.0  # coarser than production (1m) to keep test files tiny
TILE_SIDE_PX = 300  # 300 * 5m = 1500m per side, matching real VGIN tile size


def build_tile(base_dir, tile_id, project_year, x_min, y_max, veg_source, seed):
    chm = make_synthetic_chm(TILE_SIDE_PX, TILE_SIDE_PX, seed=seed)
    mask = (chm >= MIN_CANOPY_HEIGHT_M).astype(np.uint8)

    write_geotiff(f"{base_dir}/geotiff/{tile_id}_chm.tif", chm,
                   x_min, y_max, RESOLUTION_M, SOURCE_CRS_PROJ4)
    write_geotiff(f"{base_dir}/canopy_mask/{tile_id}_canopy_mask.tif", mask,
                   x_min, y_max, RESOLUTION_M, SOURCE_CRS_PROJ4)

    centroids = make_centroids_for_tile(tile_id, project_year, x_min, y_max,
                                         RESOLUTION_M, chm, n_trees=150, seed=seed)
    n_trees = len(centroids)
    cover_row = make_cover_row(tile_id, project_year, n_trees, veg_source, seed=seed)
    return cover_row, centroids


def build_county(county_name, tiles, base_dir):
    """tiles: list of (tile_id, project_year, x_min, y_max, veg_source, seed)"""
    all_cover = []
    all_centroids = []
    for tile_id, project_year, x_min, y_max, veg_source, seed in tiles:
        cover_row, centroids = build_tile(base_dir, tile_id, project_year,
                                           x_min, y_max, veg_source, seed)
        all_cover.append(cover_row)
        all_centroids.extend(centroids)

    write_csv(f"{base_dir}/{county_name}_canopy_cover.csv", all_cover, COVER_FIELDS)
    write_csv(f"{base_dir}/{county_name}_centroids.csv", all_centroids, CENTROID_FIELDS)
    print(f"{county_name}: {len(all_cover)} tiles, {len(all_centroids)} centroids -> {base_dir}")


# ── Charlottesville: unsharded, real-ish extent based on tile S13_4889_10 ──
# (x_min/y_max derived earlier in this project from that tile's actual
# ft->m converted bounds)
charlottesville_dir = f"{OUT_ROOT}/Charlottesville"
build_county("Charlottesville", [
    ("S13_4889_10", "2016", 3499111.0, 1187203.0, "derived_hag", 1),
    ("S13_4889_20", "2016", 3500637.0, 1187203.0, "derived_hag", 2),
    ("S13_4879_30", "2016", 3499111.0, 1188728.0, "derived_hag", 3),
], charlottesville_dir)

# ── Albemarle: sharded example, part_aa and part_ab (3 tiles each) ──
# Offset further north/east so the two test counties don't visually overlap.
albemarle_part_aa = f"{OUT_ROOT}/Albemarle/part_aa"
build_county("Albemarle", [
    ("S13_4921_30", "2016", 3483000.0, 1156718.0, "derived_hag", 11),
    ("S13_4922_40", "2016", 3484500.0, 1156718.0, "derived_hag", 12),
    ("S13_4923_30", "2016", 3483000.0, 1158218.0, "derived_hag", 13),
], albemarle_part_aa)

albemarle_part_ab = f"{OUT_ROOT}/Albemarle/part_ab"
build_county("Albemarle", [
    ("17SQC3129", "2014", 3486000.0, 1156718.0, "classified", 21),
    ("17SQC3130", "2014", 3487500.0, 1156718.0, "classified", 22),
    ("17SOC885120", "2020", 3486000.0, 1158218.0, "derived_hag", 23),
], albemarle_part_ab)

print("\nDone. Copy the 'data' folder into <project>/public/ so Vite serves")
print("it at /data in dev mode (matching config.ts's dev-mode DATA_BASE_URL).")
