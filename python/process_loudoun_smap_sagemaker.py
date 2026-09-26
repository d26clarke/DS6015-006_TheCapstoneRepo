"""
SageMaker Processing Job script: SMAP soil moisture download + subset for
Loudoun County, VA
-------------------------------------------------------------------------
Headless SageMaker adaptation of the original download_smapData_loudoun.py
example. SMAP does not contain canopy height/cover data -- this script is
for the separate soil-moisture side of the project (e.g. as an ancillary
covariate alongside the GEDI-derived canopy metrics), and its raw/subset
outputs are archived under a different S3 prefix (SMAP/) than the canopy
outputs (chm/, centroids/).

Differences from the original script:
  1. Non-interactive Earthdata login via EARTHDATA_USERNAME /
     EARTHDATA_PASSWORD env vars (earthaccess.login() would hang waiting
     for stdin in a Processing container).
  2. The bbox subset in the original script was a commented-out sketch
     (`da_clipped = da.sel(latitude=..., longitude=...)`) that wouldn't
     actually run against SMAP's 2D EASE-Grid lat/lon arrays. This
     version does the subset for real, by masking on the 2D
     latitude/longitude datasets rather than assuming a 1D coordinate
     index.
  3. Both the raw downloaded .h5 granules and the small bbox-subset CSV
     are uploaded to S3 rather than left on local disk, since a
     Processing container's filesystem doesn't persist after the job.

Container dependencies (requirements.txt for the ScriptProcessor):
    earthaccess
    h5py
    numpy
    boto3

Usage inside the container:
    python process_loudoun_smap_sagemaker.py \
        --bbox -77.9633 38.8488 -77.3240 39.3216 \
        --start-date 2026-05-01 --end-date 2026-05-05 \
        --s3-bucket loudoun-county-virginia-tree-canopy-project \
        --smap-raw-prefix SMAP/raw --smap-subset-prefix SMAP/subsets
"""
import argparse
import json
import multiprocessing
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime

import boto3
import h5py
import numpy as np

PROCESSING_OUTPUT_DIR = "/opt/ml/processing/output"
RESOURCE_CONFIG_PATH = "/opt/ml/config/resourceconfig.json"

# Worker count per instance type (vCPUs minus 2 for OS overhead)
INSTANCE_WORKERS = {
    "ml.c5.large":    2,
    "ml.c5.xlarge":   2,
    "ml.c5.2xlarge":  3,
    "ml.c5.4xlarge":  7,
    "ml.c5.9xlarge":  34,
    "ml.c5.18xlarge": 70,
}


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--bbox", nargs=4, type=float, required=True,
                   metavar=("min_lon", "min_lat", "max_lon", "max_lat"),
                   help="Loudoun County bbox, e.g. -77.9633 38.8488 -77.3240 39.3216")
    p.add_argument("--start-date", required=True)
    p.add_argument("--end-date", required=True)
    p.add_argument("--s3-bucket", required=True)
    p.add_argument("--smap-raw-prefix", default="SMAP/raw",
                   help="S3 prefix for archiving the raw downloaded .h5 granules")
    p.add_argument("--smap-subset-prefix", default="SMAP/subsets",
                   help="S3 prefix for the bbox-clipped soil moisture CSV")
    p.add_argument("--pass-group", default="Soil_Moisture_Retrieval_Data_AM",
                   choices=["Soil_Moisture_Retrieval_Data_AM", "Soil_Moisture_Retrieval_Data_PM"],
                   help="Which overpass (AM/PM) group to read")
    p.add_argument("--instance-type", default=None,
                   help="ml.* instance type this job is running on, for worker-count lookup. "
                        "If omitted, the script tries to read it from the SageMaker Processing "
                        "resource config, falling back to (cpu_count - 2).")
    return p.parse_args()


def get_worker_count(instance_type):
    """Look up a worker count for parallel per-granule processing. Priority:
    1) --instance-type arg matched against INSTANCE_WORKERS
    2) current_instance_type read from the Processing job's resource config
    3) local CPU count minus 2, floored at 1
    """
    if instance_type and instance_type in INSTANCE_WORKERS:
        return INSTANCE_WORKERS[instance_type]

    if instance_type:
        print(f"'{instance_type}' not in INSTANCE_WORKERS; falling back to cpu_count - 2.")

    if os.path.exists(RESOURCE_CONFIG_PATH):
        try:
            with open(RESOURCE_CONFIG_PATH) as f:
                config = json.load(f)
            detected = config.get("current_instance_type")
            if detected in INSTANCE_WORKERS:
                return INSTANCE_WORKERS[detected]
        except (json.JSONDecodeError, OSError) as e:
            print(f"Could not read {RESOURCE_CONFIG_PATH}: {e}")

    return max(1, multiprocessing.cpu_count() - 2)


def login_earthdata():
    """Non-interactive login for a headless container."""
    import earthaccess
    if not (os.environ.get("EARTHDATA_USERNAME") and os.environ.get("EARTHDATA_PASSWORD")):
        sys.exit(
            "EARTHDATA_USERNAME / EARTHDATA_PASSWORD not set. Pass them to the "
            "ScriptProcessor via env=, or pull them from Secrets Manager before "
            "invoking this script."
        )
    earthaccess.login(strategy="environment")
    return earthaccess


def fetch_smap_granules(earthaccess, bbox, start_date, end_date, local_path):
    print("Searching for SMAP granules...")
    results = earthaccess.search_data(
        short_name="SPL3SMP_E",
        version="006",
        bbox=bbox,
        temporal=(start_date, end_date),
    )
    print(f"Found {len(results)} granules matching your criteria.")
    os.makedirs(local_path, exist_ok=True)
    return earthaccess.download(results, local_path=local_path)


def subset_soil_moisture(file_path, bbox, pass_group):
    """Mask SMAP's 2D EASE-Grid lat/lon arrays to the bbox and return the
    matching (lon, lat, soil_moisture) points. Returns [] if the group or
    expected datasets aren't present in this granule."""
    min_lon, min_lat, max_lon, max_lat = bbox
    with h5py.File(file_path, "r") as f:
        if pass_group not in f:
            return []
        g = f[pass_group]
        try:
            soil_moisture = g["soil_moisture"][:]
            latitude = g["latitude"][:]
            longitude = g["longitude"][:]
        except KeyError:
            return []

        valid = soil_moisture != -9999.0  # SMAP fill value
        in_bbox = (
            (longitude >= min_lon) & (longitude <= max_lon)
            & (latitude >= min_lat) & (latitude <= max_lat)
        )
        mask = valid & in_bbox

        lons = longitude[mask]
        lats = latitude[mask]
        values = soil_moisture[mask]
        return list(zip(lons.tolist(), lats.tolist(), values.tolist()))


def write_subset_csv(points, out_path):
    import csv

    with open(out_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["longitude", "latitude", "soil_moisture_m3m3"])
        writer.writerows(points)


def upload_to_s3(local_path, bucket, key):
    s3 = boto3.client("s3")
    s3.upload_file(local_path, bucket, key)
    print(f"Uploaded s3://{bucket}/{key}")


def process_one_granule(args_tuple):
    """Top-level (picklable) worker: archive the raw granule, subset it to
    the bbox, and upload the subset CSV. Runs in a separate process, so
    each file is handled independently -- no shared state to combine."""
    file_path, bbox, pass_group, run_stamp, subset_dir, bucket, raw_prefix, subset_prefix = args_tuple
    base_name = os.path.splitext(os.path.basename(file_path))[0]

    upload_to_s3(file_path, bucket, f"{raw_prefix}/{os.path.basename(file_path)}")

    try:
        points = subset_soil_moisture(file_path, bbox, pass_group)
        if not points:
            print(f"No in-bbox soil moisture points found in {base_name}.")
            return

        csv_name = f"{base_name}_loudoun_subset_{run_stamp}.csv"
        csv_path = os.path.join(subset_dir, csv_name)
        write_subset_csv(points, csv_path)
        upload_to_s3(csv_path, bucket, f"{subset_prefix}/{csv_name}")

    except Exception as e:
        print(f"Could not subset {base_name}: {e}. Raw file was still archived.")


def main():
    args = parse_args()
    bbox = tuple(args.bbox)

    earthaccess = login_earthdata()
    downloaded_files = fetch_smap_granules(earthaccess, bbox, args.start_date, args.end_date, "/tmp/smap_downloads")

    subset_dir = os.path.join(PROCESSING_OUTPUT_DIR, "smap_subsets")
    os.makedirs(subset_dir, exist_ok=True)

    run_stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

    h5_files = [f for f in downloaded_files if f.endswith(".h5")]
    tasks = [
        (f, bbox, args.pass_group, run_stamp, subset_dir, args.s3_bucket, args.smap_raw_prefix, args.smap_subset_prefix)
        for f in h5_files
    ]

    n_workers = get_worker_count(args.instance_type)
    n_workers = max(1, min(n_workers, len(tasks))) if tasks else 1
    print(f"Processing {len(tasks)} granule(s) with {n_workers} worker process(es).")

    if tasks:
        with ProcessPoolExecutor(max_workers=n_workers) as executor:
            futures = [executor.submit(process_one_granule, t) for t in tasks]
            for future in as_completed(futures):
                future.result()  # surface any worker exception

    print("Done.")


if __name__ == "__main__":
    main()
