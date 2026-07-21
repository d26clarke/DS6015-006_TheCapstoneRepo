"""
launch_sagemaker_job.py
======================================================================
Launcher script to submit LiDAR processing jobs to AWS SageMaker.

County and year are derived automatically from the S3 input path:
  s3://central-virginia-tree-canopy-project/data/inputs/<County>/CentralVA_LiDAR_<County>.csv

The processing script receives the full S3 input path as an environment
variable (SM_INPUT_CSV_S3) and parses county and year from it at runtime.

Usage — single county:
  python launch_sagemaker_job.py --county Albemarle

Usage — all nine counties in parallel:
  python launch_sagemaker_job.py --all

Usage — override instance type:
  python launch_sagemaker_job.py --county Nelson --instance-type ml.c5.2xlarge
"""

import argparse
import time
import sagemaker
from sagemaker.processing import ScriptProcessor, ProcessingInput, ProcessingOutput
from sagemaker import get_execution_role

# ── Constants ─────────────────────────────────────────────────────────────────
BUCKET         = "central-virginia-tree-canopy-project"
S3_INPUT_BASE  = f"s3://{BUCKET}/data/inputs"
S3_OUTPUT_BASE = f"s3://{BUCKET}/data/outputs"

# County → CSV filename mapping derived from the S3 listing
COUNTY_CSV_MAP = {
    "Albemarle":       "CentralVA_LiDAR_Albemarle.csv",
    "Augusta":         "CentralVA_LiDAR_Augusta.csv",
    "Buckingham":      "CentralVA_LiDAR_Buckingham.csv",
    "Charlottesville": "CentralVA_LiDAR_Charlottesville.csv",
    "Fluvanna":        "CentralVA_LiDAR_Fluvanna.csv",
    "Greene":          "CentralVA_LiDAR_Greene.csv",
    "Louisa":          "CentralVA_LiDAR_Louisa.csv",
    "Nelson":          "CentralVA_LiDAR_Nelson.csv",
    "Rockingham":      "CentralVA_LiDAR_Rockingham.csv",
}

# Recommended instance type per county based on CSV file size proxy for tile count
COUNTY_INSTANCE_MAP = {
    "Albemarle":       "ml.c5.4xlarge",
    "Augusta":         "ml.c5.4xlarge",
    "Buckingham":      "ml.c5.2xlarge",
    "Charlottesville": "ml.c5.2xlarge",
    "Fluvanna":        "ml.c5.2xlarge",
    "Greene":          "ml.c5.2xlarge",
    "Louisa":          "ml.c5.4xlarge",
    "Nelson":          "ml.c5.2xlarge",
    "Rockingham":      "ml.c5.4xlarge",
}

# Worker count per instance type (vCPUs minus 2 for OS overhead)
INSTANCE_WORKERS = {
    "ml.c5.large":    2,
    "ml.c5.xlarge":   2,
    "ml.c5.2xlarge":  6,
    "ml.c5.4xlarge":  14,
    "ml.c5.9xlarge":  34,
    "ml.c5.18xlarge": 70,
}


def submit_job(county: str, instance_type: str, role: str, session: sagemaker.Session) -> str:
    """
    Submit a SageMaker Processing Job for a single county.
    County and year are derived inside the processing script from the input path.
    Returns the SageMaker job name.
    """
    csv_filename = COUNTY_CSV_MAP[county]
    s3_input_csv = f"{S3_INPUT_BASE}/{county}/{csv_filename}"
    s3_output    = f"{S3_OUTPUT_BASE}/{county}/"
    workers      = INSTANCE_WORKERS.get(instance_type, 6)

    print(f"\n[{county}] Submitting job")
    print(f"  Input CSV   : {s3_input_csv}")
    print(f"  Output path : {s3_output}")
    print(f"  Instance    : {instance_type}  ({workers} workers)")

    processor = ScriptProcessor(
        image_uri=sagemaker.image_uris.retrieve(
            "sklearn", session.boto_region_name, version="1.0-1"
        ),
        command=["python3"],
        role=role,
        instance_count=1,
        instance_type=instance_type,
        base_job_name=f"lidar-{county.lower()}",
        sagemaker_session=session,
        volume_size_in_gb=150,
        # Pass the S3 source path as an environment variable so the processing
        # script can parse county and year from it without CLI arguments.
        env={"SM_INPUT_CSV_S3": s3_input_csv},
    )

    inputs = [
        ProcessingInput(
            source=s3_input_csv,
            destination="/opt/ml/processing/input",
            input_name="tile_list",
        )
    ]

    outputs = [
        ProcessingOutput(
            source="/opt/ml/processing/output",
            destination=s3_output,
            output_name="processed_data",
        )
    ]

    # No --county or --year arguments — the processing script derives them
    # from SM_INPUT_CSV_S3 and the input directory structure at runtime.
    processor.run(
        code="sagemaker_process_lidar.py",
        inputs=inputs,
        outputs=outputs,
        arguments=[
            "--csv",     f"/opt/ml/processing/input/{csv_filename}",
            "--workers", str(workers),
        ],
        wait=False,
    )

    job_name = processor.latest_job.name
    print(f"  Job name    : {job_name}")
    return job_name


def main():
    parser = argparse.ArgumentParser(
        description="Submit VGIN LiDAR SageMaker Processing Jobs per county"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--county",
        choices=list(COUNTY_CSV_MAP.keys()),
        help="Process a single county",
    )
    group.add_argument(
        "--all",
        action="store_true",
        help="Submit jobs for all nine counties in parallel",
    )
    parser.add_argument(
        "--instance-type", default=None,
        help="Override the default instance type for the selected county/counties",
    )
    parser.add_argument(
        "--role", default=None,
        help="IAM Role ARN (defaults to SageMaker execution role)",
    )
    args = parser.parse_args()

    session = sagemaker.Session()
    role    = args.role if args.role else get_execution_role()

    counties = list(COUNTY_CSV_MAP.keys()) if args.all else [args.county]
    submitted_jobs = {}

    for county in counties:
        instance_type = args.instance_type or COUNTY_INSTANCE_MAP[county]
        try:
            job_name = submit_job(county, instance_type, role, session)
            submitted_jobs[county] = job_name
            if args.all:
                time.sleep(2)   # Brief pause to avoid API throttling
        except Exception as e:
            print(f"  [ERROR] Failed to submit job for {county}: {e}")
            submitted_jobs[county] = "FAILED"

    # Summary
    print("\n" + "=" * 60)
    print("  SUBMISSION SUMMARY")
    print("=" * 60)
    for county, job_name in submitted_jobs.items():
        status = "submitted" if job_name != "FAILED" else "FAILED"
        print(f"  {county:<20} {status:<12} {job_name}")
    print("=" * 60)
    region = session.boto_region_name
    print("\nMonitor jobs in the AWS SageMaker Console:")
    print(f"  https://{region}.console.aws.amazon.com/sagemaker/home?region={region}#/processing-jobs")


if __name__ == "__main__":
    main()
