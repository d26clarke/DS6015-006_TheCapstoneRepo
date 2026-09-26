"""
launch_gedi_canopy_job.py
======================================================================
Launcher script to submit the Loudoun County GEDI L2A+L2B canopy
height/cover processing job to AWS SageMaker Processing.

Follows the same ScriptProcessor + pre-built-image pattern as
launch_gedi_sample_job.py, rather than FrameworkProcessor -- no
auto-installed requirements.txt here, so IMAGE_URI below must already
have earthaccess, h5py, scipy, rasterio, and boto3 available. If your
existing tested image is missing earthaccess, add:
    RUN pip install earthaccess
to its Dockerfile and rebuild/push before using this launcher. (A
runtime `pip install` fallback, for testing without rebuilding, is
noted as a commented-out option at the top of
process_loudoun_canopy_gedi_sagemaker.py -- not recommended for
repeated production runs: no caching, and a silent failure mode if
PyPI is unreachable from the job.)

Unlike launch_gedi_sample_job.py's 02A/02B scripts, this job reads
directly from NASA Earthdata (not from GEDI files already staged in
S3) and produces two outputs from one combined run -- L2A height and
L2B cover are joined per-shot inside the same job, so there's one job
per invocation, not one per product.

Credentials:
    NASA Earthdata credentials are pulled from AWS Secrets Manager at
    submission time and passed to the job as environment variables.
    Note these are visible to anyone able to call DescribeProcessingJob
    on your account -- for tighter security, have the processing script
    call Secrets Manager itself at runtime instead (needs
    secretsmanager:GetSecretValue on the job's execution role).

    Create the secret once:
        aws secretsmanager create-secret \
            --name earthdata-credentials \
            --secret-string '{"username":"YOUR_USER","password":"YOUR_PASS"}'

Usage:
  python launch_gedi_canopy_job.py
  python launch_gedi_canopy_job.py --instance-type ml.c5.9xlarge --download-batch-size 40
  python launch_gedi_canopy_job.py --start-date 2022-01-01 --end-date 2022-12-31
"""

import argparse
import json

import boto3
import sagemaker
from sagemaker.processing import ScriptProcessor, ProcessingOutput
from sagemaker import get_execution_role

# ── Constants ────────────────────────────────────────────────────────────
BUCKET = "loudoun-county-virginia-tree-canopy-project"

# Matching the hardcoded-image-uri pattern from launch_gedi_sample_job.py --
# replace with your own tested image's account ID / repo / tag.
AWS_ACCOUNT_ID = "389548781850"
AWS_REGION = "us-east-1"
IMAGE_URI = f"{AWS_ACCOUNT_ID}.dkr.ecr.{AWS_REGION}.amazonaws.com/loudoun-gedi-processor:latest"

SCRIPT_NAME = "process_loudoun_canopy_gedi_sagemaker.py"
EARTHDATA_SECRET_NAME = "earthdata-credentials"

DEFAULT_INSTANCE_TYPE = "ml.c5.4xlarge"
DEFAULT_VOLUME_SIZE_GB = 100  # dedicated to this job, independent of any
                              # Notebook instance's own (typically much
                              # smaller) disk
DEFAULT_DOWNLOAD_THREADS = 16
DEFAULT_DOWNLOAD_BATCH_SIZE = 20
DEFAULT_MIN_SENSITIVITY = 0.9
DEFAULT_GRID_RESOLUTION_M = 30.0

DEFAULT_BBOX = ["-77.9633", "38.8488", "-77.3240", "39.3216"]
DEFAULT_START_DATE = "2019-04-01"
DEFAULT_END_DATE = "2023-03-31"


def get_earthdata_credentials(secret_name: str, region: str) -> tuple[str, str]:
    client = boto3.client("secretsmanager", region_name=region)
    secret = json.loads(client.get_secret_value(SecretId=secret_name)["SecretString"])
    return secret["username"], secret["password"]


def submit_job(args, role: str, session: sagemaker.Session) -> str:
    earthdata_username, earthdata_password = get_earthdata_credentials(EARTHDATA_SECRET_NAME, AWS_REGION)

    print("\nSubmitting GEDI L2A+L2B canopy job")
    print(f"  Image             : {IMAGE_URI}")
    print(f"  Bbox              : {args.bbox}")
    print(f"  Date range        : {args.start_date} to {args.end_date}")
    print(f"  Output (chm)      : s3://{BUCKET}/GEDI/outputs/chm")
    print(f"  Output (centroids): s3://{BUCKET}/GEDI/outputs/centroids")
    print(f"  Raw archive       : s3://{BUCKET}/GEDI")
    print(f"  Instance          : {args.instance_type}")
    print(f"  Volume size (GB)  : {args.volume_size_gb}")
    print(f"  Download batch    : {args.download_batch_size}")

    processor = ScriptProcessor(
        image_uri=IMAGE_URI,
        command=["python3"],
        role=role,
        instance_count=1,
        instance_type=args.instance_type,
        volume_size_in_gb=args.volume_size_gb,
        base_job_name="loudoun-gedi-canopy",
        sagemaker_session=session,
        env={
            "EARTHDATA_USERNAME": earthdata_username,
            "EARTHDATA_PASSWORD": earthdata_password,
        },
    )

    # A single ProcessingOutput synced to the bucket root: the script writes
    # to /opt/ml/processing/output/<chm|centroids>/, so this lands those two
    # subfolders directly at s3://<bucket>/GEDI/outputs/chm and s3://<bucket>/GEDI/outputs/centroids --
    # matching what the script's own direct boto3 uploads already write to
    # (belt-and-suspenders, same pattern as launch_gedi_sample_job.py's
    # single "gedi_output" channel).
    outputs = [
        ProcessingOutput(
            source="/opt/ml/processing/output",
            destination=f"s3://{BUCKET}/GEDI/outputs",
            output_name="gedi_canopy_output",
        )
    ]

    processor.run(
        code=SCRIPT_NAME,
        outputs=outputs,
        arguments=[
            "--bbox", *args.bbox,
            "--start-date", args.start_date,
            "--end-date", args.end_date,
            "--s3-bucket", BUCKET,
            "--chm-prefix", "chm",
            "--centroids-prefix", "centroids",
            "--gedi-raw-prefix", "GEDI",
            "--instance-type", args.instance_type,
            "--download-threads", str(args.download_threads),
            "--download-batch-size", str(args.download_batch_size),
            "--min-sensitivity", str(args.min_sensitivity),
            "--grid-resolution-m", str(args.grid_resolution_m),
        ],
        wait=False,
    )

    job_name = processor.latest_job.name
    print(f"  Job name          : {job_name}")
    return job_name


def main():
    parser = argparse.ArgumentParser(
        description="Submit the Loudoun County GEDI L2A+L2B canopy SageMaker Processing job"
    )
    parser.add_argument("--bbox", nargs=4, default=DEFAULT_BBOX,
                         metavar=("min_lon", "min_lat", "max_lon", "max_lat"))
    parser.add_argument("--start-date", default=DEFAULT_START_DATE)
    parser.add_argument("--end-date", default=DEFAULT_END_DATE)
    parser.add_argument("--instance-type", default=DEFAULT_INSTANCE_TYPE,
                         help=f"SageMaker instance type (default: {DEFAULT_INSTANCE_TYPE})")
    parser.add_argument("--volume-size-gb", type=int, default=DEFAULT_VOLUME_SIZE_GB)
    parser.add_argument("--download-threads", type=int, default=DEFAULT_DOWNLOAD_THREADS)
    parser.add_argument("--download-batch-size", type=int, default=DEFAULT_DOWNLOAD_BATCH_SIZE)
    parser.add_argument("--min-sensitivity", type=float, default=DEFAULT_MIN_SENSITIVITY)
    parser.add_argument("--grid-resolution-m", type=float, default=DEFAULT_GRID_RESOLUTION_M)
    parser.add_argument("--role", default=None,
                         help="IAM Role ARN (defaults to SageMaker execution role)")
    args = parser.parse_args()

    session = sagemaker.Session()
    role = args.role if args.role else get_execution_role()

    try:
        job_name = submit_job(args, role, session)
        status = "submitted"
    except Exception as e:
        print(f"  [ERROR] Failed to submit job: {e}")
        job_name, status = "FAILED", "FAILED"

    print("\n" + "=" * 60)
    print("  SUBMISSION SUMMARY")
    print("=" * 60)
    print(f"  {'Loudoun GEDI Canopy (L2A+L2B)':<32} {status:<12} {job_name}")
    print("=" * 60)

    region = session.boto_region_name
    print("\nMonitor the job in the AWS SageMaker Console:")
    print(f"  https://{region}.console.aws.amazon.com/sagemaker/home?region={region}#/processing-jobs")


if __name__ == "__main__":
    main()
