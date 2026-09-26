"""
SageMaker Processing Job script: Loudoun County, VA canopy height/cover
from GEDI L2A + L2B
-------------------------------------------------------------------------
Supersedes the earlier SMAP-based placeholder: SPL3SMP_E is soil moisture
and has no canopy attributes. GEDI is the right product for this --

  - GEDI02_A (L2A): per-shot relative height metrics (rh0..rh100). rh100
    is the standard proxy for canopy top height.
  - GEDI02_B (L2B): per-shot canopy cover fraction, plant area index (PAI),
    foliage height diversity, etc.

Both products are along-track LIDAR *footprints*, not a raster -- each
shot already has its own lat/lon, so it's naturally a "centroid" (the
center of that ~25 m footprint). This script:

  1. Logs into NASA Earthdata non-interactively (same reasoning as the
     SMAP example: no stdin in a Processing container, so credentials
     come from EARTHDATA_USERNAME / EARTHDATA_PASSWORD env vars).
  2. Searches + downloads GEDI02_A and GEDI02_B granules over the
     Loudoun County bbox.
  3. Parses each beam group in the HDF5 files, filters to good-quality
     shots inside the bbox, and joins L2A height to L2B cover on
     shot_number.
  4. Writes the joined per-shot records as a GeoJSON point layer
     ("centroids") -- this is the ground-truth GEDI output.
  5. Also interpolates the height values onto a regular grid to produce
     a gridded canopy-height raster ("chm") for visualization / use
     alongside other raster layers. This is a smoothed surface derived
     from sparse GEDI shots, not a true wall-to-wall CHM -- treat it as
     a coarse approximation unless you fuse it with denser lidar later.
  6. Uploads both outputs to S3.

Container dependencies (requirements.txt for the ScriptProcessor):
    earthaccess
    h5py
    numpy
    scipy
    rasterio
    boto3

If running via ScriptProcessor with a pre-built image rather than
FrameworkProcessor, there's no automatic requirements.txt install --
earthaccess (and the others) must already be in the image. For a quick
test without rebuilding the image, you can uncomment the runtime-install
fallback just below the imports -- not recommended for repeated
production runs (no caching, silent-failure risk if PyPI is unreachable).

Usage inside the container:
    python process_loudoun_canopy_gedi_sagemaker.py \
        --bbox -77.9633 38.8488 -77.3240 39.3216 \
        --start-date 2026-05-01 --end-date 2026-05-05 \
        --s3-bucket loudoun-county-virginia-tree-canopy-project \
        --chm-prefix chm --centroids-prefix centroids \
        --grid-resolution-m 30
"""
import argparse
import json
import multiprocessing
import os
import sys
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from datetime import datetime

# Runtime-install fallback (test-only -- see module docstring). Must run
# before `import earthaccess` below if uncommented.
# import subprocess
# subprocess.check_call([sys.executable, "-m", "pip", "install", "earthaccess"])

import boto3
import h5py
import numpy as np

PROCESSING_OUTPUT_DIR = "/opt/ml/processing/output"
RESOURCE_CONFIG_PATH = "/opt/ml/config/resourceconfig.json"

# GEDI full-power and coverage beam group names (same 8 for L2A and L2B)
BEAM_NAMES = [
    "BEAM0000", "BEAM0001", "BEAM0010", "BEAM0011",
    "BEAM0101", "BEAM0110", "BEAM1000", "BEAM1011",
]

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
    p.add_argument("--chm-prefix", default="chm")
    p.add_argument("--centroids-prefix", default="centroids")
    p.add_argument("--gedi-raw-prefix", default="GEDI",
                   help="S3 prefix for archiving the raw downloaded L2A/L2B granules")
    p.add_argument("--grid-resolution-m", type=float, default=30.0,
                   help="Cell size (meters, approx via degrees) for the interpolated CHM raster")
    p.add_argument("--min-sensitivity", type=float, default=0.9,
                   help="GEDI beam sensitivity threshold for usable shots")
    p.add_argument("--instance-type", default=None,
                   help="ml.* instance type this job is running on, for worker-count lookup. "
                        "If omitted, the script tries to read it from the SageMaker Processing "
                        "resource config, falling back to (cpu_count - 2).")
    p.add_argument("--download-threads", type=int, default=16,
                   help="Threads earthaccess.download() uses per batch (I/O-bound, so this "
                        "can reasonably exceed the CPU-bound worker count). L2A and L2B batches "
                        "are also downloaded concurrently with each other on top of this.")
    p.add_argument("--download-batch-size", type=int, default=20,
                   help="Granule pairs downloaded, processed, and deleted per batch. Bounds peak "
                        "local disk usage to roughly this many L2A+L2B files at once, instead of "
                        "the full download set (hundreds of GB) sitting on disk simultaneously.")
    p.add_argument("--local-staging-dir", default="/tmp",
                   help="Base directory for temporary L2A/L2B downloads. IMPORTANT: on many "
                        "SageMaker Notebook instances, /tmp is tmpfs (RAM-backed), so files staged "
                        "there consume system memory rather than disk -- point this at a real, "
                        "EBS-backed path (e.g. /home/ec2-user/SageMaker/gedi_staging on a Notebook "
                        "instance) if you see 'No space left on device' errors with /tmp showing "
                        "as tmpfs in `df -hT`.")
    return p.parse_args()


def get_worker_count(instance_type):
    """Look up a worker count for parallel granule processing. Priority:
    1) --instance-type arg matched against INSTANCE_WORKERS
    2) current_instance_type read from the Processing job's resource config
    3) local CPU count minus 2, floored at 1 (matches the table's own logic
       for instance types not in INSTANCE_WORKERS)
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


def search_gedi_granules(earthaccess, short_name, bbox, start_date, end_date):
    """Metadata-only search -- no download yet, so pairing/batching can happen first."""
    print(f"Searching for {short_name} granules...")
    results = earthaccess.search_data(
        short_name=short_name,
        version="002",
        bounding_box=bbox,
        temporal=(start_date, end_date),
    )
    print(f"Found {len(results)} {short_name} granules matching your criteria.")
    return results


def download_batch(earthaccess, results_batch, local_path, download_threads):
    os.makedirs(local_path, exist_ok=True)
    return earthaccess.download(results_batch, local_path=local_path, threads=download_threads)


def pair_results(l2a_results, l2b_results):
    """Pair L2A/L2B search results by filename stem *before* downloading
    anything, so unmatched granules are skipped without wasting bandwidth/disk."""
    def stem(result):
        try:
            return os.path.basename(result.data_links()[0]).replace("GEDI02_B", "GEDI02_A")
        except (IndexError, AttributeError):
            return None

    l2b_by_stem = {s: r for r in l2b_results if (s := stem(r))}
    pairs, unmatched = [], 0
    for l2a_result in l2a_results:
        key = stem(l2a_result)
        l2b_result = l2b_by_stem.get(key) if key else None
        if l2b_result is None:
            unmatched += 1
            continue
        pairs.append((l2a_result, l2b_result))

    if unmatched:
        print(f"{unmatched} L2A granule(s) had no matching L2B granule and will be skipped.")
    return pairs


def parse_l2a_file(file_path, bbox, min_sensitivity):
    """Return dict[shot_number] -> {lon, lat, rh100_m} for good-quality shots in bbox."""
    min_lon, min_lat, max_lon, max_lat = bbox
    records = {}
    with h5py.File(file_path, "r") as f:
        for beam in BEAM_NAMES:
            if beam not in f:
                continue
            g = f[beam]
            try:
                lat = g["lat_lowestmode"][:]
                lon = g["lon_lowestmode"][:]
                rh = g["rh"][:, 100]  # rh100, centimeters
                quality = g["quality_flag"][:]
                degrade = g["degrade_flag"][:]
                sensitivity = g["sensitivity"][:]
                shot_number = g["shot_number"][:]
            except KeyError:
                continue

            in_bbox = (lon >= min_lon) & (lon <= max_lon) & (lat >= min_lat) & (lat <= max_lat)
            good = (quality == 1) & (degrade == 0) & (sensitivity >= min_sensitivity) & in_bbox

            for sn, lo, la, h in zip(shot_number[good], lon[good], lat[good], rh[good]):
                records[int(sn)] = {"lon": float(lo), "lat": float(la), "rh100_m": float(h) / 100.0}
    return records


def parse_l2b_file(file_path, bbox, min_sensitivity):
    """Return dict[shot_number] -> {cover, pai} for good-quality shots in bbox."""
    min_lon, min_lat, max_lon, max_lat = bbox
    records = {}
    with h5py.File(file_path, "r") as f:
        for beam in BEAM_NAMES:
            if beam not in f:
                continue
            g = f[beam]
            try:
                lat = g["geolocation/lat_lowestmode"][:]
                lon = g["geolocation/lon_lowestmode"][:]
                cover = g["cover"][:]
                pai = g["pai"][:]
                quality = g["l2b_quality_flag"][:]
                sensitivity = g["sensitivity"][:]
                shot_number = g["geolocation/shot_number"][:]
            except KeyError:
                continue

            in_bbox = (lon >= min_lon) & (lon <= max_lon) & (lat >= min_lat) & (lat <= max_lat)
            good = (quality == 1) & (sensitivity >= min_sensitivity) & in_bbox

            for sn, c, p in zip(shot_number[good], cover[good], pai[good]):
                records[int(sn)] = {"cover_frac": float(c), "pai": float(p)}
    return records


def join_shots(l2a_records, l2b_records):
    """Inner-join on shot_number; height with no matching cover record is dropped."""
    joined = []
    for shot_number, a in l2a_records.items():
        b = l2b_records.get(shot_number)
        if b is None:
            continue
        joined.append({
            "shot_number": shot_number,
            "lon": a["lon"],
            "lat": a["lat"],
            "rh100_m": a["rh100_m"],
            "cover_frac": b["cover_frac"],
            "pai": b["pai"],
        })
    return joined


def write_centroids_geojson(shots, out_path):
    import json

    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [s["lon"], s["lat"]]},
            "properties": {
                "shot_number": s["shot_number"],
                "rh100_m": s["rh100_m"],
                "cover_frac": s["cover_frac"],
                "pai": s["pai"],
            },
        }
        for s in shots
    ]
    geojson = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
        "features": features,
    }
    with open(out_path, "w") as f:
        json.dump(geojson, f)


def interpolate_chm_raster(shots, bbox, resolution_m, out_path):
    """Grid the sparse GEDI rh100 points onto a regular raster via linear
    interpolation (nearest-neighbor fill for gaps), then write a GeoTIFF."""
    from scipy.interpolate import griddata
    import rasterio
    from rasterio.transform import from_origin

    if len(shots) < 4:
        print("Not enough shots to interpolate a raster; skipping CHM output for this granule.")
        return False

    min_lon, min_lat, max_lon, max_lat = bbox
    deg_per_m = 1.0 / 111320.0  # rough conversion, fine at this scale
    res_deg = resolution_m * deg_per_m

    grid_lon = np.arange(min_lon, max_lon, res_deg)
    grid_lat = np.arange(max_lat, min_lat, -res_deg)  # north -> south for raster row order
    grid_x, grid_y = np.meshgrid(grid_lon, grid_lat)

    points = np.array([[s["lon"], s["lat"]] for s in shots])
    values = np.array([s["rh100_m"] for s in shots])

    grid_z = griddata(points, values, (grid_x, grid_y), method="linear")
    nan_mask = np.isnan(grid_z)
    if nan_mask.any():
        grid_z_nn = griddata(points, values, (grid_x, grid_y), method="nearest")
        grid_z[nan_mask] = grid_z_nn[nan_mask]

    transform = from_origin(min_lon, max_lat, res_deg, res_deg)
    with rasterio.open(
        out_path, "w", driver="GTiff",
        height=grid_z.shape[0], width=grid_z.shape[1],
        count=1, dtype=grid_z.dtype, crs="EPSG:4326", transform=transform,
    ) as dst:
        dst.write(grid_z, 1)
    return True


def process_granule_pair(args_tuple):
    """Top-level (picklable) worker: parse + join one L2A/L2B granule pair.
    Runs in a separate process, so it must not touch shared state -- it
    just returns the list of joined shot dicts for the caller to combine."""
    l2a_path, l2b_path, bbox, min_sensitivity = args_tuple
    stem = os.path.basename(l2a_path)
    try:
        l2a_records = parse_l2a_file(l2a_path, bbox, min_sensitivity)
        l2b_records = parse_l2b_file(l2b_path, bbox, min_sensitivity)
        shots = join_shots(l2a_records, l2b_records)
        print(f"{stem}: {len(shots)} joined shots after quality/bbox filtering.")
        return shots
    except Exception as e:
        print(f"Could not process {stem}: {e}")
        return []


def upload_to_s3(local_path, bucket, key):
    s3 = boto3.client("s3")
    s3.upload_file(local_path, bucket, key)
    print(f"Uploaded s3://{bucket}/{key}")


def archive_raw_granules(file_paths, bucket, raw_prefix, product_subfolder):
    """Upload the untouched downloaded granules to the raw S3 archive, e.g.
    s3://<bucket>/GEDI/L2A/<filename>.h5 -- keeps raw inputs re-processable
    without re-downloading from Earthdata."""
    for path in file_paths:
        key = f"{raw_prefix}/{product_subfolder}/{os.path.basename(path)}"
        upload_to_s3(path, bucket, key)


def main():
    args = parse_args()
    bbox = tuple(args.bbox)

    earthaccess = login_earthdata()

    # Search first (metadata only -- cheap) so pairing happens before any
    # download or disk usage.
    l2a_results = search_gedi_granules(earthaccess, "GEDI02_A", bbox, args.start_date, args.end_date)
    l2b_results = search_gedi_granules(earthaccess, "GEDI02_B", bbox, args.start_date, args.end_date)
    pairs = pair_results(l2a_results, l2b_results)
    print(f"{len(pairs)} matched L2A/L2B pairs to process.")

    chm_out_dir = os.path.join(PROCESSING_OUTPUT_DIR, args.chm_prefix)
    centroids_out_dir = os.path.join(PROCESSING_OUTPUT_DIR, args.centroids_prefix)
    os.makedirs(chm_out_dir, exist_ok=True)
    os.makedirs(centroids_out_dir, exist_ok=True)

    run_stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    n_workers = get_worker_count(args.instance_type)

    l2a_dir = os.path.join(args.local_staging_dir, "gedi_l2a")
    l2b_dir = os.path.join(args.local_staging_dir, "gedi_l2b")
    batch_size = args.download_batch_size
    total_batches = (len(pairs) + batch_size - 1) // batch_size if pairs else 0

    all_shots = []
    for batch_idx in range(total_batches):
        batch = pairs[batch_idx * batch_size:(batch_idx + 1) * batch_size]
        print(f"--- Batch {batch_idx + 1}/{total_batches}: {len(batch)} granule pair(s) ---")

        l2a_batch_results = [p[0] for p in batch]
        l2b_batch_results = [p[1] for p in batch]

        # Download this batch's L2A and L2B files concurrently with each
        # other; earthaccess.download() also threads internally within a
        # batch (threads=args.download_threads).
        with ThreadPoolExecutor(max_workers=2) as fetch_executor:
            l2a_future = fetch_executor.submit(download_batch, earthaccess, l2a_batch_results, l2a_dir, args.download_threads)
            l2b_future = fetch_executor.submit(download_batch, earthaccess, l2b_batch_results, l2b_dir, args.download_threads)
            l2a_paths = l2a_future.result()
            l2b_paths = l2b_future.result()

        # Archive raw granules for this batch before processing.
        archive_raw_granules(l2a_paths, args.s3_bucket, args.gedi_raw_prefix, "L2A")
        archive_raw_granules(l2b_paths, args.s3_bucket, args.gedi_raw_prefix, "L2B")

        # Parse + join this batch's pairs in parallel across CPU workers.
        tasks = [(l2a_p, l2b_p, bbox, args.min_sensitivity) for l2a_p, l2b_p in zip(l2a_paths, l2b_paths)]
        batch_workers = max(1, min(n_workers, len(tasks)))
        with ProcessPoolExecutor(max_workers=batch_workers) as executor:
            futures = [executor.submit(process_granule_pair, t) for t in tasks]
            for future in as_completed(futures):
                all_shots.extend(future.result())

        # Free disk before the next batch -- this is what fixes running out
        # of space when the full raw dataset (hundreds of GB) is larger than
        # local storage. Only the current batch's files are ever on disk.
        for path in l2a_paths + l2b_paths:
            try:
                os.remove(path)
            except OSError as e:
                print(f"Could not remove {path}: {e}")

    if not all_shots:
        print("No usable GEDI shots found for this bbox/date range.")
        return

    centroids_name = f"gedi_loudoun_centroids_{run_stamp}.geojson"
    centroids_path = os.path.join(centroids_out_dir, centroids_name)
    write_centroids_geojson(all_shots, centroids_path)
    upload_to_s3(centroids_path, args.s3_bucket, f"{args.centroids_prefix}/{centroids_name}")

    chm_name = f"gedi_loudoun_chm_{run_stamp}.tif"
    chm_path = os.path.join(chm_out_dir, chm_name)
    if interpolate_chm_raster(all_shots, bbox, args.grid_resolution_m, chm_path):
        upload_to_s3(chm_path, args.s3_bucket, f"{args.chm_prefix}/{chm_name}")

    print("Done.")


if __name__ == "__main__":
    main()
