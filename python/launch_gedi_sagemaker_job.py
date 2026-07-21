"""
launch_gedi_sagemaker_job.py
======================================================================
Launcher script to submit GEDI L2A (canopy height) and/or L2B (canopy
cover) processing jobs to AWS SageMaker Processing.

Unlike the LiDAR pipeline's launcher, no ProcessingInput is needed here --
process_gedi02A_from_s3.py / process_gedi02B_from_s3.py each discover their
own input .h5 files directly from S3 via boto3's list_objects_v2 paginator
at runtime, rather than reading a pre-built tile-list CSV.

A ProcessingOutput channel IS still needed, though: the scripts explicitly
upload the county-summary and detailed CSVs to S3 themselves via boto3, but
the Parquet (multi-year point extract) and NetCDF (SMAP-grid) outputs are
only ever written to local disk -- without a ProcessingOutput syncing
/opt/ml/processing/output back to S3, those two files would be silently
lost when the container tears down at job end.

Usage — canopy height (GEDI L2A) only:
  python launch_gedi_sagemaker_job.py --product 02A

Usage — canopy cover (GEDI L2B) only:
  python launch_gedi_sagemaker_job.py --product 02B

Usage — both, submitted in parallel:
  python launch_gedi_sagemaker_job.py --product both

Usage — override instance type or worker count:
  python launch_gedi_sagemaker_job.py --product 02A --instance-type ml.r5.4xlarge --workers 24
"""

import argparse
import time

import sagemaker
from sagemaker.processing import ScriptProcessor, ProcessingOutput
from sagemaker import get_execution_role

# ── Constants ─────────────────────────────────────────────────────────────────
BUCKET = "central-virginia-tree-canopy-project"
S3_OUTPUT_BASE = f"s3://{BUCKET}/gedi-processing-output"

# Hardcoded, matching the same pattern already used (and proven working) in
# launch_sagemaker_job.py for the LiDAR pipeline's image_uri, rather than
# deriving the account ID programmatically.
AWS_ACCOUNT_ID = "389548781850"
AWS_REGION = "us-east-1"
IMAGE_URI = f"{AWS_ACCOUNT_ID}.dkr.ecr.{AWS_REGION}.amazonaws.com/gedi-processor:latest"

# Per-product configuration: script filename, default S3 prefix for source
# .h5 files, and a description for logging. These match each script's own
# argparse defaults -- overriding is only needed if you want to point at a
# non-default S3 location.
PRODUCT_CONFIG = {
    "02A": {
        "script": "process_gedi02A_from_s3.py",
        "description": "GEDI Level 2A (Canopy Height)",
        "s3_prefix": "GEDI/GEDI02_A/002/",
    },
    "02B": {
        "script": "process_gedi02B_from_s3.py",
        "description": "GEDI Level 2B (Canopy Cover)",
        "s3_prefix": "GEDI/GEDI02_B/002/",
    },
}

# GEDI processing is memory-hungry: concurrent HDF5 downloads (each
# potentially hundreds of MB), geopandas spatial joins, and xarray/NetCDF
# gridding all coexist in memory simultaneously. Defaulting to a
# memory-optimized instance rather than the LiDAR pipeline's compute-focused
# c5 family -- override with --instance-type if a given run needs more.
DEFAULT_INSTANCE_TYPE = "ml.r5.2xlarge"
DEFAULT_WORKERS = 16


def submit_job(product: str, instance_type: str, workers: int,
                role: str, session: sagemaker.Session) -> str:
    """
    Submit a SageMaker Processing Job for one GEDI product (02A or 02B).
    Returns the SageMaker job name.
    """
    config = PRODUCT_CONFIG[product]
    s3_output = f"{S3_OUTPUT_BASE}/{product}/"

    print(f"\n[{product}] Submitting job — {config['description']}")
    print(f"  Image       : {IMAGE_URI}")
    print(f"  Source      : s3://{BUCKET}/{config['s3_prefix']}")
    print(f"  Output      : {s3_output}")
    print(f"  Instance    : {instance_type}")
    print(f"  Workers     : {workers}")

    processor = ScriptProcessor(
        image_uri=IMAGE_URI,
        command=["python3"],
        role=role,
        instance_count=1,
        instance_type=instance_type,
        base_job_name=f"gedi-{product.lower()}",
        sagemaker_session=session,
        volume_size_in_gb=100,
    )

    outputs = [
        ProcessingOutput(
            source="/opt/ml/processing/output",
            destination=s3_output,
            output_name="gedi_output",
        )
    ]

    processor.run(
        code=config["script"],
        outputs=outputs,
        arguments=[
            "--bucket", BUCKET,
            "--s3-prefix", config["s3_prefix"],
            "--output-dir", "/opt/ml/processing/output",
            "--workers", str(workers),
        ],
        wait=False,
    )

    job_name = processor.latest_job.name
    print(f"  Job name    : {job_name}")
    return job_name


def main():
    parser = argparse.ArgumentParser(
        description="Submit GEDI L2A/L2B SageMaker Processing Jobs"
    )
    parser.add_argument(
        "--product",
        choices=["02A", "02B", "both"],
        required=True,
        help="Which GEDI product to process: 02A (canopy height), "
             "02B (canopy cover), or both (submits both jobs in parallel)",
    )
    parser.add_argument(
        "--instance-type", default=DEFAULT_INSTANCE_TYPE,
        help=f"SageMaker instance type (default: {DEFAULT_INSTANCE_TYPE})",
    )
    parser.add_argument(
        "--workers", type=int, default=DEFAULT_WORKERS,
        help=f"Concurrent download/processing workers (default: {DEFAULT_WORKERS})",
    )
    parser.add_argument(
        "--role", default=None,
        help="IAM Role ARN (defaults to SageMaker execution role)",
    )
    args = parser.parse_args()

    session = sagemaker.Session()
    role = args.role if args.role else get_execution_role()

    products = ["02A", "02B"] if args.product == "both" else [args.product]
    submitted_jobs = {}

    for product in products:
        try:
            job_name = submit_job(product, args.instance_type, args.workers, role, session)
            submitted_jobs[product] = job_name
            if len(products) > 1:
                time.sleep(2)  # brief pause to avoid API throttling
        except Exception as e:
            print(f"  [ERROR] Failed to submit job for {product}: {e}")
            submitted_jobs[product] = "FAILED"

    # Summary
    print("\n" + "=" * 60)
    print("  SUBMISSION SUMMARY")
    print("=" * 60)
    for product, job_name in submitted_jobs.items():
        status = "submitted" if job_name != "FAILED" else "FAILED"
        print(f"  {PRODUCT_CONFIG[product]['description']:<28} {status:<12} {job_name}")
    print("=" * 60)

    region = session.boto_region_name
    print("\nMonitor jobs in the AWS SageMaker Console:")
    print(f"  https://{region}.console.aws.amazon.com/sagemaker/home?region={region}#/processing-jobs")


if __name__ == "__main__":
    main()
