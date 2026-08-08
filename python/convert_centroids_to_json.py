#!/usr/bin/env python3
"""
convert_centroids_to_json.py
======================================================================
Converts per-tile centroid CSV files (centroids_raw/<TILE_ID>_centroids.csv)
to JSON, in place on S3 (same folder, new .json extension alongside the
original .csv by default).

Why: CSV has no strict schema, so a forgiving parser can silently
"succeed" at parsing something that isn't real data at all -- this is
exactly what happened when CloudFront returned an HTML fallback page with
a 200 status for a missing file, and Papa.parse quietly produced garbage
rows instead of failing. JSON.parse has no equivalent failure mode: it
throws immediately and unambiguously on non-JSON content (like an HTML
error page), so switching formats eliminates that entire bug class rather
than just working around it with a schema-validation guard.

Handles both sharded counties (part_aa/centroids_raw/...) and unsharded
ones (centroids_raw/ directly under the county), auto-detecting each
county's structure -- no per-county hardcoding, matching the same pattern
established elsewhere in this project.

Runs concurrently (ThreadPoolExecutor) since a single county can have
hundreds of individual tile files under centroids_raw/.

By default, ONLY WRITES new .json files -- never deletes or modifies the
original .csv files. Pass --delete-csv (only after verifying the JSON
output) to remove the originals afterward.

Usage:
    # Dry run first -- always do this before a real run
    python convert_centroids_to_json.py \\
        --bucket central-va-tree-canopy-dashboard \\
        --prefix data/lidar/ \\
        --dry-run

    # Real run, JSON alongside existing CSVs
    python convert_centroids_to_json.py \\
        --bucket central-va-tree-canopy-dashboard \\
        --prefix data/lidar/

    # Limit to specific counties while testing
    python convert_centroids_to_json.py \\
        --bucket central-va-tree-canopy-dashboard \\
        --prefix data/lidar/ \\
        --counties Albemarle \\
        --dry-run

    # Real run, then remove the original CSVs once verified
    python convert_centroids_to_json.py \\
        --bucket central-va-tree-canopy-dashboard \\
        --prefix data/lidar/ \\
        --delete-csv
"""

import argparse
import io
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import boto3
from botocore.config import Config
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

PART_RE = re.compile(r"^part_([a-z]+)$")


def list_county_folders(s3, bucket, prefix):
    paginator = s3.get_paginator("list_objects_v2")
    counties = set()
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix, Delimiter="/"):
        for cp in page.get("CommonPrefixes", []):
            name = cp["Prefix"][len(prefix):].rstrip("/")
            if name:
                counties.add(name)
    return sorted(counties)


def list_part_folders(s3, bucket, county_prefix):
    paginator = s3.get_paginator("list_objects_v2")
    parts = []
    for page in paginator.paginate(Bucket=bucket, Prefix=county_prefix, Delimiter="/"):
        for cp in page.get("CommonPrefixes", []):
            name = cp["Prefix"][len(county_prefix):].rstrip("/")
            if PART_RE.match(name):
                parts.append(name)
    return sorted(parts)


def list_centroid_csv_keys(s3, bucket, centroids_raw_prefix):
    paginator = s3.get_paginator("list_objects_v2")
    keys = []
    for page in paginator.paginate(Bucket=bucket, Prefix=centroids_raw_prefix):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith("_centroids.csv"):
                keys.append(obj["Key"])
    return keys


def convert_one(s3, bucket, csv_key, dry_run: bool, delete_csv: bool):
    """Convert a single <TILE_ID>_centroids.csv to <TILE_ID>_centroids.json."""
    json_key = csv_key[:-4] + ".json"  # swap .csv -> .json

    try:
        obj = s3.get_object(Bucket=bucket, Key=csv_key)
        df = pd.read_csv(io.BytesIO(obj["Body"].read()))
    except Exception as exc:
        return {"csv_key": csv_key, "status": "error", "detail": f"read/parse failed: {exc}"}

    records = json.loads(df.to_json(orient="records"))  # preserves exact column names/types

    if dry_run:
        return {"csv_key": csv_key, "json_key": json_key, "status": "dry_run", "rows": len(records)}

    try:
        s3.put_object(
            Bucket=bucket, Key=json_key,
            Body=json.dumps(records).encode("utf-8"),
            ContentType="application/json",
        )
    except Exception as exc:
        return {"csv_key": csv_key, "status": "error", "detail": f"upload failed: {exc}"}

    if delete_csv:
        try:
            s3.delete_object(Bucket=bucket, Key=csv_key)
        except Exception as exc:
            return {"csv_key": csv_key, "json_key": json_key, "status": "converted_but_delete_failed",
                    "rows": len(records), "detail": str(exc)}

    return {"csv_key": csv_key, "json_key": json_key, "status": "converted", "rows": len(records)}


def process_county(s3, bucket, county, county_prefix, dry_run: bool, delete_csv: bool, max_workers: int):
    parts = list_part_folders(s3, bucket, county_prefix)
    centroid_raw_prefixes = (
        [f"{county_prefix}{part}/centroids_raw/" for part in parts]
        if parts
        else [f"{county_prefix}centroids_raw/"]
    )

    all_csv_keys = []
    for crp in centroid_raw_prefixes:
        all_csv_keys.extend(list_centroid_csv_keys(s3, bucket, crp))

    log.info(f"[{county}] Found {len(all_csv_keys)} centroid CSV file(s) across "
             f"{len(parts) if parts else 1} location(s)")

    if not all_csv_keys:
        return {"converted": 0, "errors": 0}

    converted, errors = 0, 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(convert_one, s3, bucket, key, dry_run, delete_csv): key
            for key in all_csv_keys
        }
        for i, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            if result["status"] in ("converted", "dry_run"):
                converted += 1
            else:
                errors += 1
                log.warning(f"[{county}] {result['csv_key']}: {result.get('detail', result['status'])}")
            if i % 100 == 0 or i == len(all_csv_keys):
                log.info(f"[{county}] Processed {i}/{len(all_csv_keys)} file(s)...")

    return {"converted": converted, "errors": errors}


def main():
    parser = argparse.ArgumentParser(description="Convert per-tile centroid CSVs to JSON on S3")
    parser.add_argument("--bucket", default="central-va-tree-canopy-dashboard")
    parser.add_argument("--prefix", default="data/lidar/")
    parser.add_argument("--counties", default=None,
                         help="Comma-separated list to limit processing (default: all counties found)")
    parser.add_argument("--dry-run", action="store_true",
                         help="Report what would be converted without writing/deleting anything")
    parser.add_argument("--delete-csv", action="store_true",
                         help="After a successful conversion, delete the original .csv. "
                              "Off by default -- only use after verifying the JSON output.")
    parser.add_argument("--max-workers", type=int, default=16,
                         help="Concurrent conversion workers per county (default: 16)")
    args = parser.parse_args()

    if not args.prefix.endswith("/"):
        args.prefix += "/"

    # boto3's default S3 client caps its connection pool at 10 -- with
    # concurrent worker threads (max_workers, default 16) sharing this same
    # client, more than 10 simultaneous requests means boto3 has to discard
    # and recreate connections rather than reuse them (seen in a real run as
    # repeated "Connection pool is full, discarding connection" warnings).
    # Not a correctness issue -- 0 errors either way -- but pure wasted
    # TCP/TLS handshake overhead. Size the pool with headroom above the
    # actual worker count to eliminate the thrashing entirely.
    s3_config = Config(max_pool_connections=max(20, args.max_workers * 2))
    s3 = boto3.client("s3", config=s3_config)

    all_counties = list_county_folders(s3, args.bucket, args.prefix)
    if args.counties:
        wanted = set(c.strip() for c in args.counties.split(","))
        all_counties = [c for c in all_counties if c in wanted]

    log.info(f"Found {len(all_counties)} county folder(s) under s3://{args.bucket}/{args.prefix}")
    if args.dry_run:
        log.info("DRY RUN -- no files will be written or deleted")

    total_converted, total_errors = 0, 0
    for county in all_counties:
        county_prefix = f"{args.prefix}{county}/"
        result = process_county(s3, args.bucket, county, county_prefix,
                                 args.dry_run, args.delete_csv, args.max_workers)
        total_converted += result["converted"]
        total_errors += result["errors"]

    log.info(f"Done. {total_converted} file(s) converted, {total_errors} error(s).")


if __name__ == "__main__":
    main()
