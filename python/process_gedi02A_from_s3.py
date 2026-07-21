#!/usr/bin/env python3
"""
process_gedi02A_from_s3.py
======================================================================
GEDI Level 2A (Canopy Height) Pipeline — converted from
process_gedi_from_s3.ipynb into a standalone script runnable as a
SageMaker Processing Job.

Why this conversion happened: the notebook's kernel was repeatedly
restarting before all cells could complete. Root causes identified and
fixed here (see full explanation in the accompanying chat, not repeated
inline for every fix):

  1. Nothing in a notebook session is ever freed between cells -- every
     downloaded HDF5 byte string, every intermediate DataFrame, every
     spatial-join copy stays resident for the whole session. This script
     lets intermediate objects fall out of scope and be garbage collected
     once no longer needed, and is meant to run in a SageMaker Processing
     Job with an instance size chosen for this workload rather than a
     notebook instance sized for interactive exploration.
  2. A real crash (`ValueError: 'index_right' cannot be a column name`)
     was patched reactively in the notebook -- after it happened -- by
     reloading a CSV from disk and re-running the ENTIRE spatial join a
     second time just to recover lost in-memory state. Fixed here by
     applying the stale-index-column guard BEFORE the join, once, so the
     join never needs to run twice.
  3. The notebook computed the row-level joined GeoDataFrame and the
     aggregated county summary from the SAME single join (both are
     available from one `gpd.sjoin` call) -- but then redundantly redid
     the whole join a second time later just for the "detailed" output.
     This script performs the join exactly once and derives both outputs
     from it.

Phases (same four phases as the original notebook):
  Phase 1  — High-performance concurrent batch extraction of GEDI shots from S3
  Phase 1a — Year parsing from GEDI filenames
  Phase 1b — Harmonization to the SMAP ~9km grid
  Phase 1c — Spatial join to assign shots to study-area jurisdictions

Usage (local or inside a SageMaker Processing Job):
    python process_gedi02A_from_s3.py \\
        --bucket central-virginia-tree-canopy-project \\
        --s3-prefix GEDI/GEDI02_A/002/ \\
        --output-dir /opt/ml/processing/output \\
        --workers 16
"""

import argparse
import io
import logging
import os
import re
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

import boto3
import geopandas as gpd
import h5py
import numpy as np
import pandas as pd
import s3fs

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [PID %(process)d] %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 0 — Configuration
# ══════════════════════════════════════════════════════════════════════════════

# ── Spatial bounds (Virginia study area) ──────────────────────────────────────
MIN_LON, MIN_LAT, MAX_LON, MAX_LAT = -79.1721, 37.3296, -77.6873, 38.4755

# ── SMAP grid resolution (~9 km) ──────────────────────────────────────────────
GRID_RES = 0.081

# ── Target jurisdictions (Name, State FIPS, County/Place FIPS, Type) ──────────
TARGET_JURISDICTIONS = [
    ("Albemarle",       "51", "003",   "county"),
    ("Augusta",         "51", "015",   "county"),
    ("Buckingham",      "51", "029",   "county"),
    ("Charlottesville", "51", "14968", "place"),
    ("Fluvanna",        "51", "065",   "county"),
    ("Greene",          "51", "079",   "county"),
    ("Louisa",          "51", "109",   "county"),
    ("Nelson",          "51", "125",   "county"),
    ("Orange",          "51", "137",   "county"),
    ("Rockingham",      "51", "165",   "county"),
]


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — Helper functions
# ══════════════════════════════════════════════════════════════════════════════

def parse_year_from_filename(filename: str):
    """Extract the year from a standard GEDI filename (e.g., GEDI02_A_2022143...)."""
    year_match = re.search(r"GEDI02_A_(\d{4})", filename)
    if year_match:
        return int(year_match.group(1))
    return None


def fetch_boundary(name: str, state_fips: str, geo_id: str, geo_type: str) -> gpd.GeoDataFrame:
    """Fetch boundary GeoJSON directly from the US Census TIGERweb API."""
    if geo_type == "place":
        url = (
            "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/"
            "Places_CouSub_ConCity_SubMCD/MapServer/4/query"
            f"?where=STATE='{state_fips}'+AND+PLACE='{geo_id}'"
            "&outFields=NAME,STATE,PLACE&f=geojson&outSR=4326"
        )
    else:
        url = (
            "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/"
            "State_County/MapServer/11/query"
            f"?where=STATE='{state_fips}'+AND+COUNTY='{geo_id}'"
            "&outFields=NAME,STATE,COUNTY&f=geojson&outSR=4326"
        )
    logger.info(f"Fetching boundary for {name}...")
    with urllib.request.urlopen(url, timeout=20) as r:
        gdf = gpd.read_file(r)
    if gdf.empty:
        raise ValueError(f"No boundary found for {name} (FIPS {state_fips}/{geo_id})")
    gdf = gdf.set_crs("EPSG:4326")
    gdf["jurisdiction"] = name
    return gdf


def drop_stale_join_columns(*gdfs: gpd.GeoDataFrame) -> None:
    """
    Drop 'index_right'/'index_left' columns in place, if present.

    Applied BEFORE every gpd.sjoin() call in this script -- this is the
    proactive version of a fix the original notebook only applied
    reactively, after already crashing with:
        ValueError: 'index_right' cannot be a column name in the frames
        being joined
    That crash previously required reloading a CSV from disk and re-running
    the entire spatial join a second time just to recover. Applying the
    guard up front means the join only ever needs to run once.
    """
    for gdf in gdfs:
        stale_cols = [c for c in ("index_right", "index_left") if c in gdf.columns]
        if stale_cols:
            gdf.drop(columns=stale_cols, inplace=True)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — Phase 1 & 1a: Batch extraction with spatial masking and quality filtering
# ══════════════════════════════════════════════════════════════════════════════

def process_one_file(key: str, bucket: str, fs: s3fs.S3FileSystem,
                      min_lon: float, min_lat: float, max_lon: float, max_lat: float):
    """
    Download and process one GEDI02_A .h5 granule from S3, returning a list
    of per-beam DataFrames that passed spatial masking and quality filtering.
    """
    file_name = os.path.basename(key)
    results = []

    year = parse_year_from_filename(file_name)
    if not year:
        logger.warning(f"Could not parse year from {file_name}. Skipping.")
        return results

    try:
        s3_path = f"s3://{bucket}/{key}"
        with fs.open(s3_path, "rb") as f:
            raw_bytes = f.read()

        with h5py.File(io.BytesIO(raw_bytes), "r") as hf:
            beams = [k for k in hf.keys() if k.startswith("BEAM")]
            for beam in beams:
                if "lat_lowestmode" not in hf[beam]:
                    continue

                lats = hf[f"{beam}/lat_lowestmode"][:]
                lons = hf[f"{beam}/lon_lowestmode"][:]
                spatial_mask = (
                    (lons >= min_lon) & (lons <= max_lon) &
                    (lats >= min_lat) & (lats <= max_lat)
                )
                if not np.any(spatial_mask):
                    continue

                # Cheap 1D reads first -- quality_flag/sensitivity are single
                # columns, far cheaper than rh's 101-column 2D array.
                quality     = hf[f"{beam}/quality_flag"][:][spatial_mask]
                sensitivity = hf[f"{beam}/sensitivity"][:][spatial_mask]
                quality_ok  = (quality == 1) & (sensitivity > 0.9)
                if not np.any(quality_ok):
                    continue

                rh98 = hf[f"{beam}/rh"][:, 98][spatial_mask]

                rh_ok = (rh98 > 0) & (rh98 < 100)
                final_mask = quality_ok & rh_ok
                if not np.any(final_mask):
                    continue

                valid_df = pd.DataFrame({
                    "longitude":    lons[spatial_mask][final_mask],
                    "latitude":     lats[spatial_mask][final_mask],
                    "quality_flag": quality[final_mask],
                    "sensitivity":  sensitivity[final_mask],
                    "rh98":         rh98[final_mask],
                    "year":         year,
                    "file_source":  file_name,
                    "beam":         beam,
                })
                if not valid_df.empty:
                    results.append(valid_df)

    except Exception as e:
        logger.error(f"Error reading {file_name}: {e}")

    return results


def extract_gedi_dataframes(h5_keys, bucket: str, min_lon, min_lat, max_lon, max_lat,
                             max_workers: int = 16):
    """
    Concurrently download and process GEDI .h5 granules from S3, returning
    a combined list of per-beam DataFrames that passed spatial/quality filtering.
    """
    fs = s3fs.S3FileSystem(anon=False)
    all_dfs = []
    cell_start_time = time.time()
    completed = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(process_one_file, key, bucket, fs, min_lon, min_lat, max_lon, max_lat): key
            for key in h5_keys
        }
        for future in as_completed(futures):
            key = futures[future]
            try:
                file_dfs = future.result()
                all_dfs.extend(file_dfs)
            except Exception as e:
                logger.error(f"Unhandled error processing {os.path.basename(key)}: {e}")
            completed += 1
            if completed % 10 == 0:
                elapsed = time.time() - cell_start_time
                logger.info(f"Processed {completed}/{len(h5_keys)} files... "
                            f"({elapsed:.2f}s elapsed total)")

    total_elapsed = time.time() - cell_start_time
    minutes, seconds = divmod(total_elapsed, 60)
    logger.info(f"Extraction complete. Beams with valid data: {len(all_dfs)}")
    logger.info(f"Total extraction time: {int(minutes)}m {seconds:.2f}s")

    return all_dfs


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — Main pipeline
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="GEDI Level 2A (Canopy Height) processing pipeline")
    parser.add_argument("--bucket", default="central-virginia-tree-canopy-project")
    parser.add_argument("--s3-prefix", default="GEDI/GEDI02_A/002/")
    parser.add_argument("--gedi-county-s3-prefix", default="gedi-county-summary/")
    parser.add_argument("--gedi-detailed-county-s3-prefix", default="gedi-county-detailed/")
    parser.add_argument("--output-dir", default="/opt/ml/processing/output",
                         help="Local output directory (SageMaker Processing Job convention, "
                              "not the notebook-instance path /home/ec2-user/SageMaker/...)")
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    output_parquet = os.path.join(args.output_dir, "virginia_gedi_canopy_multiyear.parquet")
    output_netcdf = os.path.join(args.output_dir, "virginia_gedi_canopy_grid.nc")
    output_county_csv = os.path.join(args.output_dir, "virginia_gedi_county_summary.csv")
    output_detailed_county_csv = os.path.join(args.output_dir, "virginia_gedi_county_canopy_height.csv")

    logger.info("Configuration loaded.")
    logger.info(f"  GEDI source : s3://{args.bucket}/{args.s3_prefix}")
    logger.info(f"  Output dir  : {args.output_dir}")

    # ── Phase 1 & 1a: Discover GEDI files in S3 ──────────────────────────────
    logger.info(f"Scanning s3://{args.bucket}/{args.s3_prefix} for GEDI HDF5 files...")
    s3 = boto3.client("s3")
    paginator = s3.get_paginator("list_objects_v2")

    h5_keys = []
    for page in paginator.paginate(Bucket=args.bucket, Prefix=args.s3_prefix):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith(".h5"):
                h5_keys.append(obj["Key"])
    logger.info(f"Found {len(h5_keys)} GEDI HDF5 files.")
    if not h5_keys:
        raise RuntimeError("No GEDI HDF5 files found. Check S3 bucket/prefix settings.")

    # ── Phase 1 & 1a: Batch extraction ───────────────────────────────────────
    all_dfs = extract_gedi_dataframes(
        h5_keys, args.bucket, MIN_LON, MIN_LAT, MAX_LON, MAX_LAT,
        max_workers=args.workers,
    )
    if not all_dfs:
        raise RuntimeError("No valid GEDI shots found within the bounding box. Check S3 prefix and bbox settings.")

    df_gedi = pd.concat(all_dfs, ignore_index=True)
    del all_dfs  # free the list of per-beam DataFrames now that they're concatenated

    df_gedi.to_parquet(output_parquet, index=False)
    df_gedi.to_csv(output_detailed_county_csv, index=False)
    logger.info(f"Total valid GEDI shots saved : {len(df_gedi):,}")
    logger.info(f"Years covered                : {sorted(df_gedi['year'].unique())}")
    logger.info(f"Parquet file                 : {output_parquet}")

    # ── Phase 1b: Harmonize to the SMAP 9km grid ─────────────────────────────
    lon_bins = np.arange(MIN_LON, MAX_LON, GRID_RES)
    lat_bins = np.arange(MIN_LAT, MAX_LAT, GRID_RES)

    df_gedi["lon_grid"] = pd.cut(df_gedi["longitude"], bins=lon_bins, labels=lon_bins[:-1]).astype(float)
    df_gedi["lat_grid"] = pd.cut(df_gedi["latitude"], bins=lat_bins, labels=lat_bins[:-1]).astype(float)

    gedi_grid = df_gedi.groupby(["year", "lat_grid", "lon_grid"])["rh98"].mean().reset_index()
    ds_gedi = gedi_grid.set_index(["year", "lat_grid", "lon_grid"]).to_xarray()
    ds_gedi.to_netcdf(output_netcdf)
    logger.info(f"Grid cells produced : {len(gedi_grid):,}")
    logger.info(f"NetCDF saved to     : {output_netcdf}")
    del gedi_grid, ds_gedi

    # ── Phase 1c: Fetch jurisdiction boundaries ──────────────────────────────
    boundary_gdfs = []
    for name, st_fips, geo_id, geo_type in TARGET_JURISDICTIONS:
        try:
            boundary_gdfs.append(fetch_boundary(name, st_fips, geo_id, geo_type))
        except Exception as e:
            logger.error(f"Failed to fetch boundary for {name}: {e}")

    if not boundary_gdfs:
        raise RuntimeError("No jurisdiction boundaries fetched. Cannot perform spatial join.")

    boundaries = pd.concat(boundary_gdfs, ignore_index=True)
    logger.info(f"Boundaries fetched: {len(boundaries)} jurisdiction(s)")

    # ── Phase 1c: Spatial join and county-level aggregation ─────────────────
    # Performed ONCE -- both the detailed (row-level) and summary (aggregated)
    # outputs are derived from this single join, unlike the notebook which
    # redundantly redid the join a second time after a crash wiped memory.
    gdf_gedi = gpd.GeoDataFrame(
        df_gedi,
        geometry=gpd.points_from_xy(df_gedi.longitude, df_gedi.latitude),
        crs="EPSG:4326",
    )

    drop_stale_join_columns(gdf_gedi, boundaries)

    logger.info("Performing spatial join...")
    gedi_with_county = gpd.sjoin(
        gdf_gedi,
        boundaries[["jurisdiction", "geometry"]],
        how="inner",
        predicate="within",
    )

    gedi_county_summary = (
        gedi_with_county
        .groupby(["year", "jurisdiction"])["rh98"]
        .mean()
        .reset_index()
        .rename(columns={"rh98": "canopy_height_mean_m"})
    )
    logger.info(f"Spatial join complete. Rows in summary: {len(gedi_county_summary)}")

    # ── Save detailed output ─────────────────────────────────────────────────
    gedi_with_county.to_csv(output_detailed_county_csv, index=False)
    logger.info(f"Saved detailed output locally to : {output_detailed_county_csv}")

    # ── Save county summary output ───────────────────────────────────────────
    gedi_county_summary.to_csv(output_county_csv, index=False)
    logger.info(f"Saved county summary locally to : {output_county_csv}")

    # ── Upload both to S3 ─────────────────────────────────────────────────────
    s3_client = boto3.client("s3")

    county_csv_filename = os.path.basename(output_county_csv)
    s3_county_key = args.gedi_county_s3_prefix + county_csv_filename
    s3_client.upload_file(output_county_csv, args.bucket, s3_county_key,
                           ExtraArgs={"ContentType": "text/csv"})
    logger.info(f"Uploaded county summary to S3 : s3://{args.bucket}/{s3_county_key}")

    detailed_csv_filename = os.path.basename(output_detailed_county_csv)
    s3_detailed_key = args.gedi_detailed_county_s3_prefix + detailed_csv_filename
    s3_client.upload_file(output_detailed_county_csv, args.bucket, s3_detailed_key,
                           ExtraArgs={"ContentType": "text/csv"})
    logger.info(f"Uploaded detailed output to S3 : s3://{args.bucket}/{s3_detailed_key}")

    logger.info("All phases completed successfully!")


if __name__ == "__main__":
    main()
