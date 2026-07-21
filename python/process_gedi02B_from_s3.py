#!/usr/bin/env python3
"""
process_gedi02B_from_s3.py
======================================================================
GEDI Level 2B (Canopy Cover) Pipeline — converted from
process_gedi02_B_from_s3.ipynb into a standalone script runnable as a
SageMaker Processing Job.

Two confirmed bugs in the original notebook, fixed here:

  1. `process_one_file` was called by `extract_gedi_dataframes` but was
     NEVER DEFINED anywhere in the saved .ipynb -- it must have only ever
     existed in a live kernel's memory from an earlier interactive session
     (a classic Jupyter trap: a function defined in a cell that was later
     deleted or never saved survives only as long as the kernel does).
     Every kernel restart would wipe it permanently, causing a NameError
     on every single file on any fresh run. Reconstructed here from the
     commented-out legacy code + the debugging history left in that same
     cell, which had already discovered:
       - lat/lon live under "{beam}/geolocation/lat_lowestmode" (nested,
         unlike GEDI02_A where they're directly under the beam group)
       - the correct L2B quality flag field is "l2b_quality_flag"
       - the correct cover field name is "cover", NOT "canopy_cover"
         (confirmed by an error message embedded in the notebook's own
         commented-out debugging: "object 'canopy_cover' doesn't exist")

  2. The final cell referenced `GEDI_DETAILED_COUNTY_S3_PREFIX`, which was
     never defined in this notebook (only `GEDI02B_DETAILED_COUNTY_S3_PREFIX`
     was) -- meaning the detailed CSV upload to S3 has likely never
     actually succeeded. Fixed here.

Also carries over the same structural fixes applied to the GEDI02_A
conversion: spatial join performed once (not redundantly redone after a
crash), stale index-column guard applied proactively before every join,
and SageMaker Processing Job path conventions (/opt/ml/processing/...)
instead of the notebook-instance path (/home/ec2-user/SageMaker/...).

Usage:
    python process_gedi02B_from_s3.py \\
        --bucket central-virginia-tree-canopy-project \\
        --s3-prefix GEDI/GEDI02_B/002/ \\
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

MIN_LON, MIN_LAT, MAX_LON, MAX_LAT = -79.1721, 37.3296, -77.6873, 38.4755
GRID_RES = 0.081

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
    """Extract the year from a standard GEDI02_B filename (e.g., GEDI02_B_2022143...)."""
    year_match = re.search(r"GEDI02_B_(\d{4})", filename)
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
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            gdf = gpd.read_file(r)
        if gdf.empty:
            raise ValueError(f"No boundary found for {name}")
        gdf = gdf.set_crs("EPSG:4326")
        gdf["jurisdiction"] = name
        return gdf
    except Exception as e:
        logger.error(f"Failed to fetch boundary for {name}: {e}")
        return gpd.GeoDataFrame()


def drop_stale_join_columns(*gdfs: gpd.GeoDataFrame) -> None:
    """Drop 'index_right'/'index_left' columns in place, if present -- see
    process_gedi02A_from_s3.py's docstring for why this must run BEFORE
    every gpd.sjoin() call rather than being patched in reactively."""
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
    Download and process one GEDI02_B .h5 granule from S3, returning a list
    of per-beam DataFrames that passed spatial masking and quality filtering.

    RECONSTRUCTED -- this function was called by extract_gedi_dataframes()
    but was missing from the saved notebook entirely (see module docstring).
    Field paths/names below are taken directly from the commented-out
    legacy code and the debugging trail left in that same notebook cell.
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
                # GEDI02_B nests lat/lon under a "geolocation" sub-group,
                # unlike GEDI02_A where they're directly under the beam.
                if f"{beam}/geolocation/lat_lowestmode" not in hf:
                    continue

                lats = hf[f"{beam}/geolocation/lat_lowestmode"][:]
                lons = hf[f"{beam}/geolocation/lon_lowestmode"][:]
                spatial_mask = (
                    (lons >= min_lon) & (lons <= max_lon) &
                    (lats >= min_lat) & (lats <= max_lat)
                )
                if not np.any(spatial_mask):
                    continue

                # Cheap 1D reads first, same ordering rationale as GEDI02_A.
                quality     = hf[f"{beam}/l2b_quality_flag"][:][spatial_mask]
                sensitivity = hf[f"{beam}/sensitivity"][:][spatial_mask]
                quality_ok  = (quality == 1) & (sensitivity > 0.9)
                if not np.any(quality_ok):
                    continue

                # NOTE: the HDF5 field is named "cover", not "canopy_cover" --
                # confirmed by this exact error in the original notebook's
                # debugging history: "object 'canopy_cover' doesn't exist".
                # The output DataFrame column is still named "canopy_cover"
                # for compatibility with the downstream groupby/aggregation
                # code, which expects that column name.
                cover = hf[f"{beam}/cover"][:][spatial_mask]

                cover_ok = (cover >= 0.0) & (cover <= 1.0)
                final_mask = quality_ok & cover_ok
                if not np.any(final_mask):
                    continue

                valid_df = pd.DataFrame({
                    "longitude":        lons[spatial_mask][final_mask],
                    "latitude":         lats[spatial_mask][final_mask],
                    "l2b_quality_flag": quality[final_mask],
                    "sensitivity":      sensitivity[final_mask],
                    "canopy_cover":     cover[final_mask],
                    "year":             year,
                    "file_source":      file_name,
                    "beam":             beam,
                })
                if not valid_df.empty:
                    results.append(valid_df)

    except Exception as e:
        logger.error(f"Error reading {file_name}: {e}")

    return results


def extract_gedi_dataframes(h5_keys, bucket: str, min_lon, min_lat, max_lon, max_lat,
                             max_workers: int = 16):
    """
    Concurrently download and process GEDI02_B .h5 granules from S3,
    returning a combined list of per-beam DataFrames that passed
    spatial/quality filtering.
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
    parser = argparse.ArgumentParser(description="GEDI Level 2B (Canopy Cover) processing pipeline")
    parser.add_argument("--bucket", default="central-virginia-tree-canopy-project")
    parser.add_argument("--s3-prefix", default="GEDI/GEDI02_B/002/")
    parser.add_argument("--gedi-county-s3-prefix", default="gedi02B-county-summary/")
    parser.add_argument("--gedi-detailed-county-s3-prefix", default="gedi02B-county-detailed/")
    parser.add_argument("--output-dir", default="/opt/ml/processing/output",
                         help="Local output directory (SageMaker Processing Job convention, "
                              "not the notebook-instance path /home/ec2-user/SageMaker/...)")
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    output_parquet = os.path.join(args.output_dir, "virginia_gedi02B_canopy-cover_multiyear.parquet")
    output_netcdf = os.path.join(args.output_dir, "virginia_gedi02B_canopy-cover_grid.nc")
    output_county_csv = os.path.join(args.output_dir, "virginia_gedi02B_county-cover_summary.csv")
    output_detailed_county_csv = os.path.join(args.output_dir, "virginia_gedi02B_county_canopy_cover.csv")

    logger.info("Configuration loaded.")
    logger.info(f"  GEDI02_B source : s3://{args.bucket}/{args.s3_prefix}")
    logger.info(f"  Output dir      : {args.output_dir}")

    # ── Phase 1 & 1a: Discover GEDI02_B files in S3 ──────────────────────────
    logger.info(f"Scanning s3://{args.bucket}/{args.s3_prefix} for GEDI02_B HDF5 files...")
    s3 = boto3.client("s3")
    paginator = s3.get_paginator("list_objects_v2")

    h5_keys = []
    for page in paginator.paginate(Bucket=args.bucket, Prefix=args.s3_prefix):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith(".h5") and "GEDI02_B" in obj["Key"]:
                h5_keys.append(obj["Key"])
    logger.info(f"Found {len(h5_keys)} GEDI02_B files to process.")
    if not h5_keys:
        raise RuntimeError("No GEDI02_B HDF5 files found. Check S3 bucket/prefix settings.")

    # ── Phase 1 & 1a: Batch extraction ───────────────────────────────────────
    all_dfs = extract_gedi_dataframes(
        h5_keys, args.bucket, MIN_LON, MIN_LAT, MAX_LON, MAX_LAT,
        max_workers=args.workers,
    )
    if not all_dfs:
        raise RuntimeError("No valid GEDI02_B shots found within the bounding box. Check S3 prefix and bbox settings.")

    df_gedi = pd.concat(all_dfs, ignore_index=True)
    del all_dfs

    df_gedi.to_parquet(output_parquet, index=False)
    logger.info(f"Total valid GEDI shots saved : {len(df_gedi):,}")
    logger.info(f"Years covered                : {sorted(df_gedi['year'].unique())}")
    logger.info(f"Parquet file                 : {output_parquet}")

    # ── Phase 1b: Harmonize to the SMAP 9km grid ─────────────────────────────
    lon_bins = np.arange(MIN_LON, MAX_LON + GRID_RES, GRID_RES)
    lat_bins = np.arange(MIN_LAT, MAX_LAT + GRID_RES, GRID_RES)

    df_gedi["lon_grid"] = pd.cut(df_gedi["longitude"], bins=lon_bins, labels=lon_bins[:-1]).astype(float)
    df_gedi["lat_grid"] = pd.cut(df_gedi["latitude"], bins=lat_bins, labels=lat_bins[:-1]).astype(float)

    gedi_grid = df_gedi.groupby(["year", "lat_grid", "lon_grid"])["canopy_cover"].mean().reset_index()
    ds_gedi = gedi_grid.set_index(["year", "lat_grid", "lon_grid"]).to_xarray()
    ds_gedi.to_netcdf(output_netcdf)
    logger.info(f"Grid cells produced : {len(gedi_grid):,}")
    logger.info(f"NetCDF saved to     : {output_netcdf}")
    del gedi_grid, ds_gedi

    # ── Phase 1c: Fetch jurisdiction boundaries ──────────────────────────────
    boundary_gdfs = []
    for name, state, fips, g_type in TARGET_JURISDICTIONS:
        b = fetch_boundary(name, state, fips, g_type)
        if not b.empty:
            boundary_gdfs.append(b)

    if not boundary_gdfs:
        raise RuntimeError("No jurisdiction boundaries fetched. Cannot perform spatial join.")

    boundaries = pd.concat(boundary_gdfs, ignore_index=True)
    logger.info(f"Boundaries fetched: {len(boundaries)} jurisdiction(s)")

    # ── Phase 1c: Spatial join and county-level aggregation ─────────────────
    # Performed ONCE, same rationale as the GEDI02_A conversion.
    gdf_points = gpd.GeoDataFrame(
        df_gedi,
        geometry=gpd.points_from_xy(df_gedi.longitude, df_gedi.latitude),
        crs="EPSG:4326",
    )

    drop_stale_join_columns(gdf_points, boundaries)

    logger.info("Performing spatial join...")
    gedi02B_with_county = gpd.sjoin(
        gdf_points,
        boundaries[["jurisdiction", "geometry"]],
        how="inner",
        predicate="within",
    )

    gedi02B_county_summary = (
        gedi02B_with_county
        .groupby(["jurisdiction", "year"])
        .agg(
            mean_canopy_cover=("canopy_cover", "mean"),
            total_valid_shots=("canopy_cover", "count"),
        )
        .reset_index()
    )
    logger.info(f"Spatial join complete. Rows in summary: {len(gedi02B_county_summary)}")

    # ── Save detailed output ─────────────────────────────────────────────────
    gedi02B_with_county.to_csv(output_detailed_county_csv, index=False)
    logger.info(f"Saved detailed output locally to : {output_detailed_county_csv}")

    # ── Save county summary output ───────────────────────────────────────────
    gedi02B_county_summary.to_csv(output_county_csv, index=False)
    logger.info(f"Saved county summary locally to : {output_county_csv}")

    # ── Upload both to S3 ─────────────────────────────────────────────────────
    s3_client = boto3.client("s3")

    county_csv_filename = os.path.basename(output_county_csv)
    s3_county_key = args.gedi_county_s3_prefix + county_csv_filename
    s3_client.upload_file(output_county_csv, args.bucket, s3_county_key,
                           ExtraArgs={"ContentType": "text/csv"})
    logger.info(f"Uploaded county summary to S3 : s3://{args.bucket}/{s3_county_key}")

    # BUG FIX: original notebook used the undefined GEDI_DETAILED_COUNTY_S3_PREFIX
    # here (missing "02B") -- this upload has likely never actually succeeded.
    detailed_csv_filename = os.path.basename(output_detailed_county_csv)
    s3_detailed_key = args.gedi_detailed_county_s3_prefix + detailed_csv_filename
    s3_client.upload_file(output_detailed_county_csv, args.bucket, s3_detailed_key,
                           ExtraArgs={"ContentType": "text/csv"})
    logger.info(f"Uploaded detailed output to S3 : s3://{args.bucket}/{s3_detailed_key}")

    logger.info("All phases completed successfully!")


if __name__ == "__main__":
    main()
