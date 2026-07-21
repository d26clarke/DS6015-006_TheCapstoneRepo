"""
process_latlon_lidar_tiles_rest.py  (v4 — S3 output support) 
=============================================================
Query the VGIN REST API to find LAZ tiles for one or more GPS coordinates,
or for every tile that intersects a bounding box.

The --bbox mode issues a single spatial query against the VGIN REST endpoint
and returns all matching tile features, producing a CSV whose columns exactly
match the VGIN attribute export format:

    VComment, ProjectYea, OBJECTID_1, VLPID, TileName,
    PointCloud, PointClo_1, PointClo_2,
    DEMHost, DEMDownloa,
    ShapeSTAre, ShapeSTLen, Shape_Length, Shape_Area

Output destinations (mutually exclusive or combined)
----------------------------------------------------
  --output FILE.csv          Write CSV to a local file
  --s3 s3://bucket/prefix/   Upload CSV to S3 (requires boto3)

Usage
-----
    # Single GPS point
    python process_latlon_lidar_tiles_rest.py --lat 38.0494 --lon -78.4737

    # Bounding box — returns ALL tiles intersecting the box (single API call)
    python process_latlon_lidar_tiles_rest.py \\
        --bbox -78.5237 38.0096 -78.4463 38.0705

    # Save to local CSV
    python process_latlon_lidar_tiles_rest.py \\
        --bbox -78.5237 38.0096 -78.4463 38.0705 \\
        --output CentralVA_LiDAR_Charlottesville.csv

    # Upload directly to S3
    python process_latlon_lidar_tiles_rest.py \\
        --bbox -78.5237 38.0096 -78.4463 38.0705 \\
        --s3 s3://central-virginia-tree-canopy-project/data/outputs/Charlottesville/

    # Save locally AND upload to S3
    python process_latlon_lidar_tiles_rest.py \\
        --bbox -78.5237 38.0096 -78.4463 38.0705 \\
        --output CentralVA_LiDAR_Charlottesville.csv \\
        --s3 s3://central-virginia-tree-canopy-project/data/outputs/Charlottesville/

    # Dry-run: show what would be queried without hitting VGIN
    python process_latlon_lidar_tiles_rest.py \\
        --bbox -78.5237 38.0096 -78.4463 38.0705 --dry-run
"""

import argparse
import csv
import io
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


# ── Helper: parse an S3 URI into (bucket, key_prefix) ────────────────────────
def _parse_s3_uri(s3_uri: str) -> tuple[str, str]:
    """
    Parse 's3://bucket/some/prefix/' into ('bucket', 'some/prefix/').
    The prefix may be empty (e.g. 's3://bucket/').
    """
    if not s3_uri.startswith("s3://"):
        raise ValueError(f"Invalid S3 URI (must start with s3://): {s3_uri!r}")
    without_scheme = s3_uri[5:]          # strip 's3://'
    slash_pos = without_scheme.find("/")
    if slash_pos == -1:
        bucket = without_scheme
        prefix = ""
    else:
        bucket = without_scheme[:slash_pos]
        prefix = without_scheme[slash_pos + 1:]  # may be '' or 'some/path/'
    if not bucket:
        raise ValueError(f"S3 URI has no bucket name: {s3_uri!r}")
    return bucket, prefix


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


# ── Build CSV content as an in-memory string ──────────────────────────────────
def rows_to_csv_string(rows: list[dict]) -> str:
    """
    Serialise a list of row dicts to a CSV string (RFC 4180) using
    CSV_FIELDNAMES as the column order.  Returns the full CSV text.
    """
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_FIELDNAMES,
                            extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


# ── Write CSV to a local file ─────────────────────────────────────────────────
def write_csv_local(csv_text: str, path: str, row_count: int) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        f.write(csv_text)
    print(f"  Local file  : {path}  ({row_count} rows)")


# ── Upload CSV to S3 ──────────────────────────────────────────────────────────
def write_csv_s3(csv_text: str, s3_uri: str, filename: str, row_count: int) -> None:
    """
    Upload *csv_text* to S3.

    The final S3 key is constructed as:
        <prefix><filename>
    where <prefix> comes from the --s3 argument (e.g. 'data/outputs/Charlottesville/')
    and <filename> is derived from --output (basename) or auto-generated.

    Parameters
    ----------
    csv_text  : Full CSV content as a UTF-8 string.
    s3_uri    : Destination S3 URI, e.g. 's3://bucket/data/outputs/Charlottesville/'
    filename  : The bare filename to use as the S3 object key suffix.
    row_count : Number of data rows (for the log message).
    """
    try:
        import boto3
    except ImportError:
        print("  ERROR: boto3 is not installed.  Run:  pip install boto3",
              file=sys.stderr)
        return

    bucket, prefix = _parse_s3_uri(s3_uri)
    # Ensure prefix ends with '/' if non-empty so the filename is appended cleanly
    if prefix and not prefix.endswith("/"):
        prefix += "/"
    key = prefix + filename

    body_bytes = csv_text.encode("utf-8")

    s3_client = boto3.client("s3")
    try:
        s3_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=body_bytes,
            ContentType="text/csv",
        )
        full_s3_path = f"s3://{bucket}/{key}"
        print(f"  S3 upload   : {full_s3_path}  ({row_count} rows, "
              f"{len(body_bytes):,} bytes)")
    except Exception as exc:
        print(f"  ERROR: S3 upload failed for s3://{bucket}/{key}: {exc}",
              file=sys.stderr)


# ── Derive output filename from CLI args ──────────────────────────────────────
def _output_filename(args: argparse.Namespace) -> str:
    """
    Return the bare CSV filename to use for both local and S3 output.
    Priority:
      1. Basename of --output if provided  (e.g. 'tiles.csv')
      2. Auto-generated name based on bbox or lat/lon
    """
    import os
    if args.output:
        return os.path.basename(args.output)

    if args.bbox:
        lon_min, lat_min, lon_max, lat_max = args.bbox
        return (f"VGIN_tiles_"
                f"{lat_min:.4f}N_{abs(lon_min):.4f}W_"
                f"{lat_max:.4f}N_{abs(lon_max):.4f}W.csv")

    return f"VGIN_tile_{args.lat:.4f}N_{abs(args.lon):.4f}W.csv"


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
            if args.s3:
                bucket, prefix = _parse_s3_uri(args.s3)
                filename = _output_filename(args)
                print(f"  S3 target: s3://{bucket}/{prefix}{filename}")
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

        # Build CSV content once; reuse for both local and S3 output
        csv_text = rows_to_csv_string(rows)
        filename = _output_filename(args)

        if args.output:
            write_csv_local(csv_text, args.output, len(rows))

        if args.s3:
            write_csv_s3(csv_text, args.s3, filename, len(rows))

        if not args.output and not args.s3:
            # No output destination specified — print compact table to stdout
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
    print(f"  Format    : {attr.get('PointCloudFormat', '?')}")
    print(f"  LPC URL   : {lpc_url}")
    print("=" * 60)

    row = feature_to_csv_row(feature)
    csv_text = rows_to_csv_string([row])
    filename = _output_filename(args)

    if args.output:
        write_csv_local(csv_text, args.output, 1)

    if args.s3:
        write_csv_s3(csv_text, args.s3, filename, 1)


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
            "Save results to a local CSV file with columns matching the VGIN "
            "export format.  Can be combined with --s3."
        )
    )
    p.add_argument(
        "--s3", type=str, default=None,
        metavar="s3://BUCKET/PREFIX/",
        help=(
            "Upload results CSV directly to S3.  Provide the full S3 URI "
            "including trailing slash, e.g.: "
            "s3://central-virginia-tree-canopy-project/data/outputs/Charlottesville/  "
            "The filename is taken from --output (basename) or auto-generated.  "
            "Requires boto3 (pre-installed in SageMaker environments)."
        )
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be queried/uploaded without making any API calls."
    )

    args = p.parse_args()

    if args.lat is not None and args.lon is None:
        p.error("--lon is required when --lat is specified")

    return args


if __name__ == "__main__":
    run(parse_args())
