"""
process_latlon_lidar_tiles_rest.py
===================================
Query the VGIN REST API to find LAZ tiles for one or more GPS coordinates,
or for every tile that intersects a bounding box.

The --bbox mode issues a single spatial query against the VGIN REST endpoint
and returns all matching tile features, producing a CSV whose columns exactly
match the VGIN attribute export format:

    VComment, ProjectYea, OBJECTID_1, VLPID, TileName,
    PointCloud, PointClo_1, PointClo_2,
    DEMHost, DEMDownloa,
    ShapeSTAre, ShapeSTLen, Shape_Length, Shape_Area

Usage
-----
    # Single GPS point
    python process_latlon_lidar_tiles_rest.py --lat 38.0494 --lon -78.4737

    # Bounding box — returns ALL tiles intersecting the box (single API call)
    python process_latlon_lidar_tiles_rest.py \\
        --bbox -78.5237 38.0096 -78.4463 38.0705

    # Full 8-jurisdiction study area bbox
    python process_latlon_lidar_tiles_rest.py \\
        --bbox -79.1721 37.3296 -77.6873 38.4755

    # Dry-run: show what would be queried without hitting VGIN
    python process_latlon_lidar_tiles_rest.py \\
        --bbox -78.5237 38.0096 -78.4463 38.0705 --dry-run

    # Save results to CSV (matching VGIN export column format)
    python process_latlon_lidar_tiles_rest.py \\
        --bbox -78.5237 38.0096 -78.4463 38.0705 \\
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

# ── VGIN REST endpoint ────────────────────────────────────────────────────────
VGIN_URL = (
    "https://vginmaps.vdem.virginia.gov/arcgis/rest/services/Download/"
    "Virginia_LiDAR_Downloads/MapServer/1/query"
)

# Maximum features the VGIN REST API returns per request.
PAGE_SIZE = 1000

# CSV column names that match the target VGIN export format exactly.
CSV_FIELDNAMES = [
    "VComment", "ProjectYea", "OBJECTID_1", "VLPID", "TileName",
    "PointCloud", "PointClo_1", "PointClo_2",
    "DEMHost", "DEMDownloa",
    "ShapeSTAre", "ShapeSTLen", "Shape_Length", "Shape_Area",
]

# Actual field names returned by the VGIN REST API (outFields=*)
# Shape metrics use the unusual "Shape.STArea()" / "Shape.STLength()" keys.
SHAPE_AREA_KEY   = "Shape.STArea()"
SHAPE_LENGTH_KEY = "Shape.STLength()"


# ── Helper: strip HTML anchor tags, keep raw URL ─────────────────────────────
def _extract_url(html_or_url: str) -> str:
    """Return the bare href URL from an HTML anchor string, or the string itself."""
    if not html_or_url:
        return ""
    m = re.search(r'href=["\']([^"\']+)["\']', html_or_url)
    return m.group(1) if m else html_or_url


# ── Helper: reformat anchor to match VGIN CSV export quoting style ────────────
def _reformat_anchor(html: str) -> str:
    """
    The VGIN REST API returns anchors with backslash-escaped quotes:
        <a href=\"URL\">Label</a>

    When written by csv.writer (RFC 4180), a field value of
        <a href=""URL"">Label</a>
    becomes the on-disk text:
        "<a href=""""URL"""">Label</a>"
    which is exactly what the reference VGIN export CSV contains.

    So this function produces the field *value* (what Python holds in memory)
    with double double-quotes around the URL:  href=""URL""
    The csv.writer then handles the outer quoting automatically.
    """
    if not html:
        return ""
    # Try backslash-escaped form from REST API: href=\"URL\"
    url_m   = re.search(r'href=\\"([^\\]+)\\"', html)
    label_m = re.search(r'>([^<]+)<', html)
    if url_m and label_m:
        url   = url_m.group(1)
        label = label_m.group(1)
        return f'<a href=""{url}"">{label}</a>'
    # Fallback: try unescaped href="URL"
    url_m2 = re.search(r'href="([^"]+)"', html)
    if url_m2 and label_m:
        url   = url_m2.group(1)
        label = label_m.group(1)
        return f'<a href=""{url}"">{label}</a>'
    return html


# ── Core: query VGIN for a single GPS point ───────────────────────────────────
def find_laz_for_gps(lat: float, lon: float) -> dict | None:
    """
    Query VGIN REST API to find the LAZ tile containing (lat, lon).
    Returns a raw feature dict {'attributes': {...}} or None if not found.
    """
    params = urllib.parse.urlencode({
        "geometry":       f"{lon},{lat}",
        "geometryType":   "esriGeometryPoint",
        "inSR":           "4326",
        "spatialRel":     "esriSpatialRelIntersects",
        "outFields":      "*",
        "returnGeometry": "false",
        "f":              "json",
    })
    try:
        with urllib.request.urlopen(VGIN_URL + "?" + params, timeout=20) as r:
            data = json.load(r)
    except Exception as exc:
        print(f"  WARNING: VGIN query failed for ({lat}, {lon}): {exc}",
              file=sys.stderr)
        return None

    features = data.get("features", [])
    return features[0] if features else None


# ── Core: query VGIN for all tiles intersecting a bbox ───────────────────────
def find_laz_for_bbox(lon_min: float, lat_min: float,
                      lon_max: float, lat_max: float) -> list[dict]:
    """
    Query VGIN REST API for ALL tile features whose geometry intersects the
    given bounding box (WGS84 degrees).  Handles pagination automatically.
    Returns a list of raw feature dicts (each has 'attributes').
    """
    all_features: list[dict] = []
    offset = 0

    while True:
        params = urllib.parse.urlencode({
            "geometry":          f"{lon_min},{lat_min},{lon_max},{lat_max}",
            "geometryType":      "esriGeometryEnvelope",
            "inSR":              "4326",
            "spatialRel":        "esriSpatialRelIntersects",
            "outFields":         "*",
            "returnGeometry":    "false",
            "resultOffset":      offset,
            "resultRecordCount": PAGE_SIZE,
            "f":                 "json",
        })
        try:
            with urllib.request.urlopen(VGIN_URL + "?" + params, timeout=30) as r:
                data = json.load(r)
        except Exception as exc:
            print(f"  WARNING: VGIN bbox query failed (offset={offset}): {exc}",
                  file=sys.stderr)
            break

        features = data.get("features", [])
        all_features.extend(features)

        if len(features) < PAGE_SIZE:
            break

        offset += PAGE_SIZE
        time.sleep(0.2)

    return all_features


# ── Convert a raw VGIN feature to a CSV row dict ─────────────────────────────
def feature_to_csv_row(feature: dict) -> dict:
    """
    Map a VGIN REST API feature (attributes dict) to a CSV row dict whose
    keys match CSV_FIELDNAMES exactly.

    Column mapping (REST API field → CSV column):
        VComment             → VComment
        ProjectYear          → ProjectYea
        OBJECTID             → OBJECTID_1
        VLPID                → VLPID
        TileName             → TileName
        PointCloudHost       → PointCloud
        PointCloudFormat     → PointClo_1
        PointCloudDownload   → PointClo_2   (HTML anchor, re-quoted)
        DEMHost              → DEMHost
        DEMDownload          → DEMDownloa   (HTML anchor, re-quoted)
        Shape.STArea()       → ShapeSTAre, Shape_Area
        Shape.STLength()     → ShapeSTLen,  Shape_Length
    """
    attr = feature.get("attributes", {})

    shape_area   = attr.get(SHAPE_AREA_KEY,   "")
    shape_length = attr.get(SHAPE_LENGTH_KEY, "")

    pc_download  = _reformat_anchor(attr.get("PointCloudDownload", ""))
    dem_download = _reformat_anchor(attr.get("DEMDownload", ""))

    return {
        "VComment":     attr.get("VComment", ""),
        "ProjectYea":   attr.get("ProjectYear", ""),
        "OBJECTID_1":   attr.get("OBJECTID", ""),
        "VLPID":        attr.get("VLPID", ""),
        "TileName":     attr.get("TileName", ""),
        "PointCloud":   attr.get("PointCloudHost", ""),
        "PointClo_1":   attr.get("PointCloudFormat", ""),
        "PointClo_2":   pc_download,
        "DEMHost":      attr.get("DEMHost", ""),
        "DEMDownloa":   dem_download,
        "ShapeSTAre":   shape_area,
        "ShapeSTLen":   shape_length,
        "Shape_Length": shape_length,
        "Shape_Area":   shape_area,
    }


# ── Write CSV ─────────────────────────────────────────────────────────────────
def write_csv(rows: list[dict], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES,
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"Results saved to: {path}  ({len(rows)} rows)")


# ── Main logic ────────────────────────────────────────────────────────────────
def run(args: argparse.Namespace) -> None:

    # ── Bbox mode ─────────────────────────────────────────────────────────────
    if args.bbox:
        lon_min, lat_min, lon_max, lat_max = args.bbox
        print(f"Bounding box  : lon [{lon_min}, {lon_max}]  lat [{lat_min}, {lat_max}]")

        if args.dry_run:
            print("\n[DRY RUN] Would query VGIN for all tiles intersecting this bbox.")
            print(f"  Endpoint : {VGIN_URL}")
            print(f"  Geometry : {lon_min},{lat_min},{lon_max},{lat_max}")
            return

        print("Querying VGIN REST API …")
        features = find_laz_for_bbox(lon_min, lat_min, lon_max, lat_max)
        print(f"  → {len(features)} tile feature(s) returned")

        if not features:
            print("No tiles found for the given bounding box.")
            return

        rows = [feature_to_csv_row(f) for f in features]

        # Console summary
        print()
        print("=" * 60)
        print(f"  Tiles found   : {len(rows)}")
        years = sorted({str(r["ProjectYea"]) for r in rows if r["ProjectYea"]})
        print(f"  Project years : {', '.join(years)}")
        print("=" * 60)

        if args.output:
            write_csv(rows, args.output)
        else:
            # Print compact table to stdout
            print(f"\n{'TileName':<25}  {'Year':<6}  {'VLPID':<6}  LPC URL")
            print("-" * 90)
            for r in sorted(rows, key=lambda x: str(x["TileName"])):
                lpc_url = _extract_url(str(r["PointClo_2"]))
                print(f"  {str(r['TileName']):<23}  {str(r['ProjectYea']):<6}  "
                      f"{str(r['VLPID']):<6}  {lpc_url}")

        return

    # ── Single-point mode ─────────────────────────────────────────────────────
    lat, lon = args.lat, args.lon
    print(f"Single point  : lat={lat}  lon={lon}")

    if args.dry_run:
        print(f"\n[DRY RUN] Would query VGIN for tile at ({lat}, {lon}).")
        return

    print("Querying VGIN REST API …")
    feature = find_laz_for_gps(lat, lon)

    if not feature:
        print("No tile found for the given coordinates.")
        return

    attr = feature.get("attributes", {})
    tile    = attr.get("TileName", "?")
    year    = attr.get("ProjectYear", "?")
    lpc_url = _extract_url(str(attr.get("PointCloudDownload", "")))

    print()
    print("=" * 60)
    print(f"  Tile      : {tile}")
    print(f"  Year      : {year}")
    print(f"  VLPID     : {attr.get('VLPID', '?')}")
    print(f"  Format    : {attr.get('PointCloudFormat', '?')}")
    print(f"  LPC URL   : {lpc_url}")
    print("=" * 60)

    if args.output:
        row = feature_to_csv_row(feature)
        write_csv([row], args.output)


# ── CLI ───────────────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Query VGIN REST API to find LAZ tiles for a GPS point or "
            "all tiles intersecting a bounding box.  "
            "Output CSV matches the VGIN attribute export column format."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

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
            "Returns ALL tiles whose geometry intersects the box (single API call)."
        )
    )

    p.add_argument(
        "--lon", type=float,
        help="Longitude of a single query point (required with --lat)"
    )
    p.add_argument(
        "--output", type=str, default=None,
        metavar="FILE.csv",
        help=(
            "Save results to a CSV file with columns matching the VGIN export format: "
            "VComment, ProjectYea, OBJECTID_1, VLPID, TileName, PointCloud, "
            "PointClo_1, PointClo_2, DEMHost, DEMDownloa, "
            "ShapeSTAre, ShapeSTLen, Shape_Length, Shape_Area."
        )
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be queried without making any VGIN API calls."
    )

    args = p.parse_args()

    if args.lat is not None and args.lon is None:
        p.error("--lon is required when --lat is specified")

    return args


if __name__ == "__main__":
    run(parse_args())
