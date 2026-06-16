"""
process_latlon_lidar_tiles_rest.py
===================================
Query the VGIN REST API to find LAZ tiles for one or more GPS coordinates,
or for every grid point within a bounding box.

Usage
-----
    # Single GPS point
    python process_latlon_lidar_tiles_rest.py --lat 38.0494 --lon -78.4737

    # Bounding box (SW corner → NE corner, WGS84 degrees)
    python process_latlon_lidar_tiles_rest.py \
        --bbox -78.5237 38.0096 -78.4463 38.0705

    # Bounding box with custom grid spacing (degrees between sample points)
    python process_latlon_lidar_tiles_rest.py \
        --bbox -78.5237 38.0096 -78.4463 38.0705 \
        --spacing 0.05

    # Full 8-jurisdiction study area bbox
    python process_latlon_lidar_tiles_rest.py \
        --bbox -79.1721 37.3296 -77.6873 38.4755 \
        --spacing 0.08

    # Dry-run: show grid points without querying VGIN
    python process_latlon_lidar_tiles_rest.py \
        --bbox -78.5237 38.0096 -78.4463 38.0705 \
        --dry-run

    # Save results to CSV
    python process_latlon_lidar_tiles_rest.py \
        --bbox -78.5237 38.0096 -78.4463 38.0705 \
        --output tiles.csv
"""

import argparse
import csv
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from itertools import product

# ── VGIN REST endpoint ────────────────────────────────────────────────────────
VGIN_URL = (
    "https://vginmaps.vdem.virginia.gov/arcgis/rest/services/Download/"
    "Virginia_LiDAR_Downloads/MapServer/1/query"
)

# Default grid spacing for bbox queries (degrees).
# ~0.09° ≈ 9 km at 38°N — one sample point per SMAP pixel, avoids redundant queries.
DEFAULT_SPACING = 0.09


# ── Core query function ───────────────────────────────────────────────────────
def find_laz_for_gps(lat: float, lon: float) -> dict | None:
    """
    Query VGIN REST API to find the LAZ tile containing (lat, lon).
    Returns dict with TileName, ProjectYear, download URL, or None if not found.
    """
    params = urllib.parse.urlencode({
        "geometry":     f"{lon},{lat}",           # x,y order (lon first)
        "geometryType": "esriGeometryPoint",
        "inSR":         "4326",                   # WGS84 input
        "spatialRel":   "esriSpatialRelIntersects",
        "outFields":    "TileName,ProjectYear,PointCloudDownload,PointCloudFormat,VLPID",
        "returnGeometry": "false",
        "f":            "json",
    })
    try:
        with urllib.request.urlopen(VGIN_URL + "?" + params, timeout=20) as r:
            data = json.load(r)
    except Exception as exc:
        print(f"  WARNING: VGIN query failed for ({lat}, {lon}): {exc}", file=sys.stderr)
        return None

    features = data.get("features", [])
    if not features:
        return None

    attr = features[0]["attributes"]
    raw_url = attr.get("PointCloudDownload", "")
    match = re.search(r'href="([^"]+)"', raw_url)
    download_url = match.group(1) if match else raw_url

    return {
        "tile_name":    attr.get("TileName"),
        "project_year": attr.get("ProjectYear"),
        "format":       attr.get("PointCloudFormat"),
        "vlpid":        attr.get("VLPID"),
        "download_url": download_url,
    }


# ── Bbox grid generator ───────────────────────────────────────────────────────
def bbox_grid_points(lon_min: float, lat_min: float,
                     lon_max: float, lat_max: float,
                     spacing: float) -> list[tuple[float, float]]:
    """
    Generate a regular grid of (lat, lon) sample points within the bbox.
    Points are spaced `spacing` degrees apart in both axes.
    The grid is inset by half a spacing step so edge points fall inside the bbox.
    """
    half = spacing / 2.0
    lats = []
    lat = lat_min + half
    while lat <= lat_max:
        lats.append(round(lat, 6))
        lat += spacing

    lons = []
    lon = lon_min + half
    while lon <= lon_max:
        lons.append(round(lon, 6))
        lon += spacing

    return [(lat, lon) for lat, lon in product(lats, lons)]


# ── Main logic ────────────────────────────────────────────────────────────────
def run(args: argparse.Namespace) -> None:

    # ── Build list of (lat, lon) points to query ──────────────────────────────
    if args.bbox:
        lon_min, lat_min, lon_max, lat_max = args.bbox
        points = bbox_grid_points(lon_min, lat_min, lon_max, lat_max, args.spacing)
        print(f"Bounding box  : lon [{lon_min}, {lon_max}]  lat [{lat_min}, {lat_max}]")
        print(f"Grid spacing  : {args.spacing}°")
        print(f"Sample points : {len(points)}")
    else:
        points = [(args.lat, args.lon)]
        print(f"Single point  : lat={args.lat}  lon={args.lon}")

    if args.dry_run:
        print("\n[DRY RUN] Sample points (no VGIN queries will be made):")
        for i, (lat, lon) in enumerate(points, 1):
            print(f"  {i:4d}.  lat={lat:.6f}  lon={lon:.6f}")
        print(f"\nTotal: {len(points)} points")
        return

    # ── Query VGIN for each point, deduplicate by tile name ───────────────────
    seen_tiles: dict[str, dict] = {}   # tile_name → result dict
    point_results = []                 # one entry per query point

    print(f"\nQuerying VGIN for {len(points)} point(s) …\n")

    for i, (lat, lon) in enumerate(points, 1):
        result = find_laz_for_gps(lat, lon)

        if result:
            tile = result["tile_name"]
            status = "NEW" if tile not in seen_tiles else "DUP"
            seen_tiles[tile] = result
            point_results.append({
                "query_lat":    lat,
                "query_lon":    lon,
                "tile_name":    tile,
                "project_year": result["project_year"],
                "format":       result["format"],
                "vlpid":        result["vlpid"],
                "download_url": result["download_url"],
                "status":       status,
            })
            print(f"  [{i:4d}/{len(points)}]  ({lat:.4f}, {lon:.4f})  "
                  f"→  {tile}  ({result['project_year']})  [{status}]")
        else:
            point_results.append({
                "query_lat": lat, "query_lon": lon,
                "tile_name": None, "project_year": None,
                "format": None, "vlpid": None,
                "download_url": None, "status": "NO_DATA",
            })
            print(f"  [{i:4d}/{len(points)}]  ({lat:.4f}, {lon:.4f})  "
                  f"→  No tile found")

        # Polite delay to avoid hammering the VGIN REST service
        if i < len(points):
            time.sleep(0.15)

    # ── Summary ───────────────────────────────────────────────────────────────
    unique_tiles = {r["tile_name"] for r in point_results if r["tile_name"]}
    no_data      = sum(1 for r in point_results if r["status"] == "NO_DATA")

    print()
    print("=" * 60)
    print(f"  Unique tiles found : {len(unique_tiles)}")
    print(f"  Points with no tile: {no_data}")
    print("=" * 60)

    if unique_tiles:
        print("\nUnique LAZ tiles covering the requested area:")
        for tile_name, info in sorted(seen_tiles.items()):
            print(f"  {tile_name:<25}  year={info['project_year']}  "
                  f"vlpid={info['vlpid']}")
            print(f"    {info['download_url']}")

    # ── Optional CSV output ───────────────────────────────────────────────────
    if args.output:
        fieldnames = ["query_lat", "query_lon", "tile_name", "project_year",
                      "format", "vlpid", "download_url", "status"]
        with open(args.output, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(point_results)
        print(f"\nResults saved to: {args.output}")

        # Also write a deduplicated tile-only CSV
        tile_csv = args.output.replace(".csv", "_unique_tiles.csv")
        with open(tile_csv, "w", newline="") as f:
            writer = csv.DictWriter(
                f, fieldnames=["tile_name", "project_year", "format",
                               "vlpid", "download_url"]
            )
            writer.writeheader()
            for info in sorted(seen_tiles.values(), key=lambda x: x["tile_name"]):
                writer.writerow(info)
        print(f"Unique tiles saved to: {tile_csv}")


# ── CLI ───────────────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Query VGIN REST API to find LAZ tiles for a GPS point or "
            "every grid point within a bounding box."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Mutually exclusive: single point vs bbox
    loc = p.add_mutually_exclusive_group(required=True)
    loc.add_argument(
        "--lat", type=float,
        help="Latitude of a single query point (WGS84 degrees)"
    )
    loc.add_argument(
        "--bbox", nargs=4, type=float,
        metavar=("LON_MIN", "LAT_MIN", "LON_MAX", "LAT_MAX"),
        help=(
            "Bounding box in WGS84 degrees: lon_min lat_min lon_max lat_max. "
            "A regular grid of sample points is generated inside the box."
        )
    )

    p.add_argument(
        "--lon", type=float,
        help="Longitude of a single query point (required with --lat)"
    )
    p.add_argument(
        "--spacing", type=float, default=DEFAULT_SPACING,
        help=(
            f"Grid spacing in degrees for bbox queries "
            f"(default: {DEFAULT_SPACING}° ≈ 9 km at 38°N). "
            "Smaller values produce more sample points and may find more tiles."
        )
    )
    p.add_argument(
        "--output", type=str, default=None,
        metavar="FILE.csv",
        help="Save full results to a CSV file. Also writes a deduplicated tile CSV."
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Print grid points without making any VGIN queries."
    )

    args = p.parse_args()

    # Validate: --lon is required when --lat is given
    if args.lat is not None and args.lon is None:
        p.error("--lon is required when --lat is specified")

    return args


if __name__ == "__main__":
    run(parse_args())

