#!/usr/bin/env python3
"""
merge_sharded_county_outputs.py
======================================================================
Combines a county's sharded SageMaker job outputs (part_aa/, part_ab/,
... part_aj/) back into a single, flat structure at the county root --
matching the layout an unsharded county (e.g. Charlottesville) already
has. This lets the React dashboard go back to simple, single-fetch
logic for every county, instead of merging shards client-side.

For each county under the given S3 prefix:
  1. Auto-detects whether the county has any part_XX/ subfolders at all.
     If not (already flat, like Charlottesville), it's skipped --
     nothing hardcodes "except Charlottesville" anywhere; a county with
     no parts is simply already in the target state.
  2. Downloads and concatenates <County>_canopy_cover.csv and
     <County>_centroids.csv across all parts found, preserving the
     ORIGINAL column schema exactly (no added tracking columns) --
     the merged file is schema-identical to what an unsharded run
     produces, so the frontend needs zero changes to read it.
  3. Server-side copies (no download/re-upload of large binary data)
     every geotiff/*.tif and canopy_mask/*.tif from each part into the
     county-root geotiff/ and canopy_mask/ folders. Safe because tile
     filenames are globally unique -- no collision risk across parts.
  4. Concatenates logs/<County>_skipped_tiles.csv across parts and
     writes an aggregated logs/<County>_run_summary.txt.
  5. Uploads everything to the county root (no part_XX/ prefix).

By default, this ONLY WRITES new, merged files -- it never deletes or
modifies the original part_XX/ folders. Pass --delete-parts explicitly
(and only after verifying the merge) to remove them afterward.

Usage:
    # Dry run first -- always do this before a real run
    python merge_sharded_county_outputs.py \\
        --bucket central-va-tree-canopy-dashboard \\
        --prefix data/lidar/ \\
        --dry-run

    # Real run, merge only, keep original part folders
    python merge_sharded_county_outputs.py \\
        --bucket central-va-tree-canopy-dashboard \\
        --prefix data/lidar/

    # Real run, merge AND remove the original part_XX/ folders afterward
    python merge_sharded_county_outputs.py \\
        --bucket central-va-tree-canopy-dashboard \\
        --prefix data/lidar/ \\
        --delete-parts

    # Limit to specific counties (comma-separated), e.g. while testing
    python merge_sharded_county_outputs.py \\
        --bucket central-va-tree-canopy-dashboard \\
        --prefix data/lidar/ \\
        --counties Albemarle,Orange \\
        --dry-run
"""

import argparse
import io
import logging
import re
from collections import defaultdict

import boto3
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

PART_RE = re.compile(r"^part_([a-z]+)$")


def list_county_folders(s3, bucket, prefix):
    """List immediate 'subfolders' directly under prefix (one per county)."""
    paginator = s3.get_paginator("list_objects_v2")
    counties = set()
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix, Delimiter="/"):
        for cp in page.get("CommonPrefixes", []):
            name = cp["Prefix"][len(prefix):].rstrip("/")
            if name:
                counties.add(name)
    return sorted(counties)


def list_part_folders(s3, bucket, county_prefix):
    """List part_XX/ subfolders under a county prefix, sorted alphabetically."""
    paginator = s3.get_paginator("list_objects_v2")
    parts = []
    for page in paginator.paginate(Bucket=bucket, Prefix=county_prefix, Delimiter="/"):
        for cp in page.get("CommonPrefixes", []):
            name = cp["Prefix"][len(county_prefix):].rstrip("/")
            if PART_RE.match(name):
                parts.append(name)
    return sorted(parts)


def list_keys(s3, bucket, prefix):
    """List all object keys under a prefix (recursive)."""
    paginator = s3.get_paginator("list_objects_v2")
    keys = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            keys.append(obj["Key"])
    return keys


def read_csv_from_s3(s3, bucket, key):
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
        return pd.read_csv(io.BytesIO(obj["Body"].read()))
    except s3.exceptions.NoSuchKey:
        return None
    except Exception as exc:
        log.warning(f"Could not read s3://{bucket}/{key}: {exc}")
        return None


def merge_county(s3, bucket, county, county_prefix, parts, dry_run: bool):
    log.info(f"[{county}] Found {len(parts)} part(s): {', '.join(parts)}")

    cover_frames, centroid_frames, skipped_frames = [], [], []
    tif_copy_plan = []  # list of (source_key, dest_key)
    run_summaries = []

    for part in parts:
        part_prefix = f"{county_prefix}{part}/"

        cover_key = f"{part_prefix}{county}_canopy_cover.csv"
        df = read_csv_from_s3(s3, bucket, cover_key)
        if df is not None:
            cover_frames.append(df)
            log.info(f"  {part}: {len(df)} row(s) in canopy_cover.csv")
        else:
            log.warning(f"  {part}: no {county}_canopy_cover.csv found")

        centroid_key = f"{part_prefix}{county}_centroids.csv"
        df = read_csv_from_s3(s3, bucket, centroid_key)
        if df is not None:
            centroid_frames.append(df)
            log.info(f"  {part}: {len(df)} row(s) in centroids.csv")

        skipped_key = f"{part_prefix}logs/{county}_skipped_tiles.csv"
        df = read_csv_from_s3(s3, bucket, skipped_key)
        if df is not None:
            skipped_frames.append(df)

        summary_key = f"{part_prefix}logs/{county}_run_summary.txt"
        try:
            obj = s3.get_object(Bucket=bucket, Key=summary_key)
            run_summaries.append((part, obj["Body"].read().decode("utf-8")))
        except s3.exceptions.NoSuchKey:
            pass

        for kind in ("geotiff", "canopy_mask"):
            source_keys = list_keys(s3, bucket, f"{part_prefix}{kind}/")
            for source_key in source_keys:
                filename = source_key.rsplit("/", 1)[-1]
                dest_key = f"{county_prefix}{kind}/{filename}"
                tif_copy_plan.append((source_key, dest_key))

    # ── Merge CSVs, preserving the original schema exactly ──────────────────
    merged_cover = pd.concat(cover_frames, ignore_index=True) if cover_frames else None
    merged_centroids = pd.concat(centroid_frames, ignore_index=True) if centroid_frames else None
    merged_skipped = pd.concat(skipped_frames, ignore_index=True) if skipped_frames else None

    if merged_cover is not None:
        log.info(f"[{county}] Merged canopy_cover.csv: {len(merged_cover)} total row(s)")
    if merged_centroids is not None:
        log.info(f"[{county}] Merged centroids.csv: {len(merged_centroids)} total row(s)")
    if merged_skipped is not None:
        log.info(f"[{county}] Merged skipped_tiles.csv: {len(merged_skipped)} total row(s)")
    log.info(f"[{county}] {len(tif_copy_plan)} geotiff/canopy_mask file(s) to copy to county root")

    if dry_run:
        log.info(f"[{county}] DRY RUN -- no files written or copied")
        return

    # ── Write merged CSVs ─────────────────────────────────────────────────────
    if merged_cover is not None:
        buf = io.StringIO()
        merged_cover.to_csv(buf, index=False)
        s3.put_object(Bucket=bucket, Key=f"{county_prefix}{county}_canopy_cover.csv",
                      Body=buf.getvalue().encode("utf-8"), ContentType="text/csv")

    if merged_centroids is not None:
        buf = io.StringIO()
        merged_centroids.to_csv(buf, index=False)
        s3.put_object(Bucket=bucket, Key=f"{county_prefix}{county}_centroids.csv",
                       Body=buf.getvalue().encode("utf-8"), ContentType="text/csv")

    if merged_skipped is not None:
        buf = io.StringIO()
        merged_skipped.to_csv(buf, index=False)
        s3.put_object(Bucket=bucket, Key=f"{county_prefix}logs/{county}_skipped_tiles.csv",
                       Body=buf.getvalue().encode("utf-8"), ContentType="text/csv")

    if run_summaries:
        combined_summary = "\n\n".join(f"=== {part} ===\n{text}" for part, text in run_summaries)
        s3.put_object(Bucket=bucket, Key=f"{county_prefix}logs/{county}_run_summary.txt",
                       Body=combined_summary.encode("utf-8"), ContentType="text/plain")

    # ── Server-side copy geotiff/canopy_mask files (no download/re-upload) ──
    for source_key, dest_key in tif_copy_plan:
        s3.copy_object(
            Bucket=bucket,
            Key=dest_key,
            CopySource={"Bucket": bucket, "Key": source_key},
        )
    log.info(f"[{county}] Copied {len(tif_copy_plan)} geotiff/canopy_mask file(s) to county root")


def delete_parts(s3, bucket, county, county_prefix, parts):
    for part in parts:
        part_prefix = f"{county_prefix}{part}/"
        keys = list_keys(s3, bucket, part_prefix)
        if not keys:
            continue
        for i in range(0, len(keys), 1000):  # delete_objects caps at 1000 per call
            batch = keys[i:i + 1000]
            s3.delete_objects(
                Bucket=bucket,
                Delete={"Objects": [{"Key": k} for k in batch]},
            )
        log.info(f"[{county}] Deleted {len(keys)} object(s) under {part_prefix}")


def main():
    parser = argparse.ArgumentParser(description="Merge sharded county LiDAR outputs back into one flat structure")
    parser.add_argument("--bucket", default="central-va-tree-canopy-dashboard")
    parser.add_argument("--prefix", default="data/lidar/")
    parser.add_argument("--counties", default=None,
                         help="Comma-separated list to limit processing (default: all counties found)")
    parser.add_argument("--dry-run", action="store_true",
                         help="Report what would happen without writing/copying anything")
    parser.add_argument("--delete-parts", action="store_true",
                         help="After a successful merge, delete the original part_XX/ folders. "
                              "Off by default -- only use after verifying the merge is correct.")
    args = parser.parse_args()

    if not args.prefix.endswith("/"):
        args.prefix += "/"

    s3 = boto3.client("s3")

    all_counties = list_county_folders(s3, args.bucket, args.prefix)
    if args.counties:
        wanted = set(c.strip() for c in args.counties.split(","))
        all_counties = [c for c in all_counties if c in wanted]

    log.info(f"Found {len(all_counties)} county folder(s) under s3://{args.bucket}/{args.prefix}")

    for county in all_counties:
        county_prefix = f"{args.prefix}{county}/"
        parts = list_part_folders(s3, args.bucket, county_prefix)

        if not parts:
            log.info(f"[{county}] No part_XX/ subfolders found -- already flat, skipping.")
            continue

        merge_county(s3, args.bucket, county, county_prefix, parts, dry_run=args.dry_run)

        if args.delete_parts and not args.dry_run:
            delete_parts(s3, args.bucket, county, county_prefix, parts)

    log.info("Done.")


if __name__ == "__main__":
    main()
