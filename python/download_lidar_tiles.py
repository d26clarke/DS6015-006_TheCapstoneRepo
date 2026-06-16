"""
download_lidar_tiles.py 
=======================
Batch download LiDAR Point Cloud (.laz / .copc.laz) and DEM (.tif) files
from the VGIN-exported CentralVA_LiDAR_SelectedTiles.csv.

CSV structure (actual columns):
  VComment    - "Current" or "Replaced VLPID..." (superseded tiles)
  ProjectYea  - Collection year (2014, 2016, 2018, 2019, 2020)
  OBJECTID_1  - Internal ArcGIS object ID
  VLPID       - VGIN LiDAR Project ID
  TileName    - Tile identifier (e.g. 17SQB485965)
  PointCloud  - Host agency: USGS or NOAA
  PointClo_1  - File format: LAZ (all rows)
  PointClo_2  - HTML anchor tag containing the LPC download URL
  DEMHost     - Host agency for DEM: USGS or blank (no DEM available)
  DEMDownloa  - HTML anchor tag containing the DEM download URL (blank if no DEM)
  ShapeSTAre, ShapeSTLen, Shape_Length, Shape_Area - geometry fields (ignored)

Usage:
  # Download LiDAR Point Clouds only (recommended first step):
  python download_lidar_tiles.py --csv CentralVA_LiDAR_SelectedTiles.csv --lpc-only

  # Download both LPC and DEM files:
  python download_lidar_tiles.py --csv CentralVA_LiDAR_SelectedTiles.csv

  # Download only tiles from a specific project year:
  python download_lidar_tiles.py --csv CentralVA_LiDAR_SelectedTiles.csv --year 2019

  # Download only "Current" tiles (skip superseded/replaced tiles):
  python download_lidar_tiles.py --csv CentralVA_LiDAR_SelectedTiles.csv --current-only

  # Dry run (print URLs without downloading):
  python download_lidar_tiles.py --csv CentralVA_LiDAR_SelectedTiles.csv --dry-run
"""

import argparse
import os
import re
import sys
import time
import pandas as pd
import requests
from pathlib import Path


# ---------------------------------------------------------------------------
# URL extraction
# ---------------------------------------------------------------------------

def extract_url(html_cell: str) -> str | None:
    """
    Extract the first HTTP/HTTPS URL from an HTML anchor tag cell.

    The CSV stores URLs as HTML like:
        <a href=""https://rockyweb.usgs.gov/.../tile.laz"">Download LPC</a>

    The double-quote encoding is an ArcGIS CSV export artefact.
    """
    if not isinstance(html_cell, str) or html_cell.strip() == "":
        return None
    match = re.search(r'(https?://[^\s"<>]+)', html_cell)
    return match.group(1) if match else None


# ---------------------------------------------------------------------------
# Download helper
# ---------------------------------------------------------------------------

def download_file(url: str, dest_path: Path, retries: int = 3, timeout: int = 120) -> bool:
    """
    Download a single file with retry logic.
    Returns True on success, False on failure.
    """
    if dest_path.exists():
        print(f"  [SKIP]  Already exists: {dest_path.name}")
        return True

    dest_path.parent.mkdir(parents=True, exist_ok=True)

    for attempt in range(1, retries + 1):
        try:
            print(f"  [GET]   {url}")
            response = requests.get(url, stream=True, timeout=timeout)
            response.raise_for_status()

            with open(dest_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=65536):
                    f.write(chunk)

            size_mb = dest_path.stat().st_size / (1024 * 1024)
            print(f"  [OK]    {dest_path.name}  ({size_mb:.1f} MB)")
            return True

        except requests.exceptions.RequestException as e:
            print(f"  [WARN]  Attempt {attempt}/{retries} failed: {e}")
            if attempt < retries:
                time.sleep(5 * attempt)

    print(f"  [FAIL]  Giving up on: {url}")
    return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Batch download LiDAR tiles from CentralVA_LiDAR_SelectedTiles.csv"
    )
    parser.add_argument(
        "--csv",
        required=True,
        help="Path to the exported CSV file from ArcGIS Pro"
    )
    parser.add_argument(
        "--output-dir",
        default="lidar_tiles_central_va",
        help="Root output directory (default: ../data/lidar_tiles_central_va)"
    )
    parser.add_argument(
        "--lpc-only",
        action="store_true",
        help="Download LiDAR Point Cloud files only (skip DEM .tif files)"
    )
    parser.add_argument(
        "--dem-only",
        action="store_true",
        help="Download DEM files only (skip LPC .laz files)"
    )
    parser.add_argument(
        "--current-only",
        action="store_true",
        help="Skip superseded tiles (only download rows where VComment == 'Current')"
    )
    parser.add_argument(
        "--year",
        type=int,
        default=None,
        help="Filter to a specific collection year (e.g. --year 2019)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print URLs without downloading anything"
    )
    args = parser.parse_args()

    # ---- Load CSV ----
    print(f"\nLoading: {args.csv}")
    dfSelectedTiles: pd.DataFrame = pd.read_csv(args.csv, encoding="utf-8-sig")
    print(f"Total rows loaded: {len(dfSelectedTiles):,}")

    # ---- Apply filters ----
    if args.current_only:
        before = len(dfSelectedTiles)
        dfSelectedTiles = dfSelectedTiles[dfSelectedTiles["VComment"].str.strip() == "Current"]
        print(f"After --current-only filter: {len(dfSelectedTiles):,} rows  (removed {before - len(dfSelectedTiles):,} superseded)")

    if args.year is not None:
        before = len(dfSelectedTiles)
        dfSelectedTiles = dfSelectedTiles[dfSelectedTiles["ProjectYea"] == args.year]
        print(f"After --year {args.year} filter: {len(dfSelectedTiles):,} rows  (removed {before - len(dfSelectedTiles):,})")

    if dfSelectedTiles.empty:
        print("No rows remain after filtering. Exiting.")
        sys.exit(0)

    # ---- Organise output directories by project year and host ----
    output_root = Path(args.output_dir)
    output_root.mkdir(parents=True, exist_ok=True)

    # ---- Counters ----
    lpc_ok = lpc_fail = lpc_skip = 0
    dem_ok = dem_fail = dem_skip = 0

    print(f"\nStarting downloads → {output_root.resolve()}\n")

    for idx, row in dfSelectedTiles.iterrows():
        tile_name = str(row["TileName"]).strip()
        project_year = str(row["ProjectYea"]).strip()
        host = str(row["PointCloud"]).strip()

        # Sub-directory: output/<year>/<host>/
        tile_dir = output_root / project_year / host

        # ---- LPC download ----
        if not args.dem_only:
            lpc_url = extract_url(str(row["PointClo_2"]))
            if lpc_url:
                ext = ".copc.laz" if ".copc.laz" in lpc_url else ".laz"
                lpc_filename = tile_dir / "LPC" / f"{tile_name}{ext}"
                if args.dry_run:
                    print(f"[DRY-RUN] LPC  {lpc_url}")
                    lpc_skip += 1
                else:
                    success = download_file(lpc_url, lpc_filename)
                    if success:
                        lpc_ok += 1
                    else:
                        lpc_fail += 1
            else:
                print(f"  [WARN]  No LPC URL for tile: {tile_name}")
                lpc_skip += 1

        # ---- DEM download ----
        if not args.lpc_only:
            dem_host = str(row["DEMHost"]).strip()
            if dem_host == "":
                # No DEM available for this tile (638 rows in dataset)
                dem_skip += 1
            else:
                dem_url = extract_url(str(row["DEMDownloa"]))
                if dem_url:
                    dem_filename = tile_dir / "DEM" / Path(dem_url).name
                    if args.dry_run:
                        print(f"[DRY-RUN] DEM  {dem_url}")
                        dem_skip += 1
                    else:
                        success = download_file(dem_url, dem_filename)
                        if success:
                            dem_ok += 1
                        else:
                            dem_fail += 1
                else:
                    print(f"  [WARN]  No DEM URL for tile: {tile_name}")
                    dem_skip += 1

    # ---- Summary ----
    print("\n============================================")
    print("Download Summary")
    print("============================================")
    if not args.dem_only:
        print(f"  LPC files:  {lpc_ok} downloaded, {lpc_fail} failed, {lpc_skip} skipped")
    if not args.lpc_only:
        print(f"  DEM files:  {dem_ok} downloaded, {dem_fail} failed, {dem_skip} skipped/unavailable")
    print(f"  Output dir: {output_root.resolve()}")
    print("============================================\n")

    if lpc_fail > 0 or dem_fail > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
