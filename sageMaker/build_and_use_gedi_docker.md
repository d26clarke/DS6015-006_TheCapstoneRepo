# Building and Using `Dockerfile.sagemaker-gedi`

Reference steps for building the GEDI processing image, pushing it to ECR, and
using it in a SageMaker Processing Job. Mirrors the same workflow already
established for `Dockerfile.sagemaker-lidar` / `lidar-processor`.

---

## 0. Prerequisites

- Docker installed and running locally (or on an EC2/CloudShell instance with
  Docker available).
- AWS CLI installed and configured with credentials that have ECR push
  permissions (`ecr:CreateRepository`, `ecr:GetAuthorizationToken`,
  `ecr:BatchCheckLayerAvailability`, `ecr:PutImage`, `ecr:InitiateLayerUpload`,
  `ecr:UploadLayerPart`, `ecr:CompleteLayerUpload`).
- Your AWS account ID and target region (`us-east-1`, matching the base image
  and existing LiDAR setup).
- `Dockerfile.sagemaker-gedi` present in your build context directory.

Set these once so the commands below can be copy-pasted as-is:

```bash
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export AWS_REGION=us-east-1
export REPO_NAME=gedi-processor
export IMAGE_TAG=latest
```

---

## 1. Create the ECR repository (one-time)

Skip this step if `gedi-processor` already exists in ECR.

```bash
aws ecr create-repository \
    --repository-name "$REPO_NAME" \
    --region "$AWS_REGION"

aws ecr create-repository --repository-name gedi-processor --region "us-east-1"
```

Verify it was created:

```bash
aws ecr describe-repositories --repository-names "$REPO_NAME" --region "$AWS_REGION"

aws ecr describe-repositories --repository-names "gedi-processor" --region "us-east-1"
```

---

## 2. Authenticate Docker to ECR

Required before both the base-image pull (from the AWS-managed scikit-learn
ECR repo) and the final push to your own repo. Token expires after 12 hours,
so re-run this if a build/push fails with an auth error after a long gap.

```bash
aws ecr get-login-password --region "$AWS_REGION" \
    | docker login --username AWS --password-stdin \
      "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"

aws ecr get-login-password --region "us-east-1" docker login --username AWS --password-stdin "389548781850.dkr.ecr.us-east-1.amazonaws.com"
```

You should see `Login Succeeded`.

---

## 3. Build the image locally

Run from the directory containing `Dockerfile.sagemaker-gedi`:

```bash
docker build \
    -f Dockerfile.sagemaker-gedi \
    -t "$REPO_NAME:$IMAGE_TAG" \
    .

docker build --platform linux/amd64 -f Dockerfile.sagemaker-gedi -t "gedi-processor:latest" .

Here are the results of the docker build : aws ecr get-login-password --region "us-east-1" | docker login --username AWS --password-stdin "389548781850.dkr.ecr.us-east-1.amazonaws.com"
WARNING! Your credentials are stored unencrypted in '/Users/ddclarke/.docker/config.json'.
Configure a credential helper to remove this warning. See
https://docs.docker.com/go/credential-store/
Login Succeeded
(base) ddclarke@GSLAL0325070029 sageMaker % docker build -f Dockerfile.sagemaker-gedi -t "gedi-processor:latest" .
[+] Building 0.1s (3/3) FINISHED                                                                docker:desktop-linux
 => [internal] load build definition from Dockerfile.sagemaker-gedi                                             0.0s
 => => transferring dockerfile: 6.09kB                                                                          0.0s
 => ERROR [internal] load metadata for 683313688378.dkr.ecr.us-east-1.amazonaws.com/sagemaker-scikit-learn:1.0  0.1s
 => [auth] sharing credentials for 683313688378.dkr.ecr.us-east-1.amazonaws.com                                 0.0s
------
 > [internal] load metadata for 683313688378.dkr.ecr.us-east-1.amazonaws.com/sagemaker-scikit-learn:1.0-1-cpu-py3:
------
Dockerfile.sagemaker-gedi:28
--------------------
  26 |     # ══════════════════════════════════════════════════════════════════════════════
  27 |     
  28 | >>> FROM 683313688378.dkr.ecr.us-east-1.amazonaws.com/sagemaker-scikit-learn:1.0-1-cpu-py3
  29 |     
  30 |     LABEL maintainer="Central Virginia Tree Canopy Project"
--------------------
ERROR: failed to build: failed to solve: 683313688378.dkr.ecr.us-east-1.amazonaws.com/sagemaker-scikit-learn:1.0-1-cpu-py3: failed to resolve source metadata for 683313688378.dkr.ecr.us-east-1.amazonaws.com/sagemaker-scikit-learn:1.0-1-cpu-py3: unexpected status from HEAD request to https://683313688378.dkr.ecr.us-east-1.amazonaws.com/v2/sagemaker-scikit-learn/manifests/1.0-1-cpu-py3: 403 Forbidden
View build details: docker-desktop://dashboard/build/desktop-linux/desktop-linux/xjnns64o8mgnfpmxc39e3y14p

SOLUTION

aws ecr get-login-password --region us-east-1 \
    | docker login --username AWS --password-stdin \
      683313688378.dkr.ecr.us-east-1.amazonaws.com

docker build --platform linux/amd64 -f Dockerfile.sagemaker-gedi -t "gedi-processor:latest" . "389548781850".dkr.ecr.us-east-1.amazonaws.com/gedi-processor:latest

ECR_REGISTRY="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
FULL_IMAGE_URI="${ECR_REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}"

"389548781850".dkr.ecr.us-east-1.amazonaws.com/gedi-processor:latest

The actual command to execute:
docker build --platform linux/amd64 -f Dockerfile.sagemaker-gedi-take3 -t "gedi-processor:latest" -t "389548781850.dkr.ecr.us-east-1.amazonaws.com/gedi-processor:latest" .

```

**Watch the build log for the final verification step's output.** The
Dockerfile's last `RUN` asserts that `boto3`, `botocore`, and `s3fs` are
exactly the pinned versions (`1.43.0`, `1.43.0`, `2026.6.0`) after everything
else installs. If a later `pip install` step silently upgraded any of them,
the build fails here with an `AssertionError` naming exactly which package
drifted — this is intentional; do not skip past it by removing the assertion.

Expected success output near the end of the build:
```
All required packages imported successfully, pinned boto stack intact.
  boto3      : 1.43.0
  botocore   : 1.43.0
  s3fs       : 2026.6.0
  h5py       : ...
  geopandas  : ...
  xarray     : ...
  numpy      : ...
```

**Common build failure to watch for:** geopandas/GDAL version mismatches.
`geopandas` depends on `fiona`/`pyogrio`, which link against the system
`libgdal-dev` installed earlier in the Dockerfile. If pip resolves a
`geopandas` version expecting a different GDAL ABI than what's installed via
`apt-get`, the build (or the import-verification step) will fail. If this
happens, either pin `geopandas` to a specific version known to match the
base image's GDAL version, or pin `libgdal-dev` to a specific version in the
`apt-get install` line.

---

## 4. Sanity-check the image locally (recommended before pushing)

Run the actual import check manually, independent of the build step, to
confirm the image works as a standalone container:

```bash
docker run --rm "$REPO_NAME:$IMAGE_TAG" python3 -c "
import boto3, botocore, s3fs, h5py, geopandas, xarray, netCDF4, pyarrow, numpy
print('boto3:', boto3.__version__)
print('botocore:', botocore.__version__)
print('s3fs:', s3fs.__version__)
print('geopandas:', geopandas.__version__)
"
```

If you have AWS credentials mounted/available to the container, you can also
smoke-test actual S3 access before committing to a full SageMaker run:

```bash
docker run --rm \
    -e AWS_ACCESS_KEY_ID \
    -e AWS_SECRET_ACCESS_KEY \
    -e AWS_SESSION_TOKEN \
    "$REPO_NAME:$IMAGE_TAG" \
    python3 -c "
import boto3
s3 = boto3.client('s3')
resp = s3.list_objects_v2(Bucket='central-virginia-tree-canopy-project', Prefix='GEDI/GEDI02_A/002/', MaxKeys=5)
for obj in resp.get('Contents', []):
    print(obj['Key'])
"
```

---

## 5. Tag the image for ECR

```bash
docker tag "$REPO_NAME:$IMAGE_TAG" \
    "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$REPO_NAME:$IMAGE_TAG"
```

---

## 6. Push to ECR

```bash
docker push "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$REPO_NAME:$IMAGE_TAG"

docker push "389548781850.dkr.ecr.us-east-1.amazonaws.com/gedi-processor:latest"

```

---

## 7. Verify the pushed image

```bash
aws ecr describe-images \
    --repository-name "$REPO_NAME" \
    --region "$AWS_REGION" \
    --query 'imageDetails[*].{Tags:imageTags,Pushed:imagePushedAt,SizeMB:imageSizeInBytes}' \
    --output table
```

Confirm the tag you expect (`latest`, or a version tag if you used one) shows
up with a recent `Pushed` timestamp.

---

## 8. Reference the image in a SageMaker Processing Job

In `launch_gedi_sagemaker_job.py` (or wherever you construct the
`ScriptProcessor`), point at the pushed image:

```python
image_uri = f"{AWS_ACCOUNT_ID}.dkr.ecr.{AWS_REGION}.amazonaws.com/gedi-processor:latest"

processor = ScriptProcessor(
    image_uri=image_uri,
    command=["python3"],
    role=role,
    instance_count=1,
    instance_type=instance_type,   # size for geopandas/xarray memory needs
    sagemaker_session=session,
)
```

**IAM note:** the SageMaker execution role used by the Processing Job needs
`ecr:GetDownloadUrlForLayer`, `ecr:BatchGetImage`, and
`ecr:GetAuthorizationToken` permissions to pull this image at job start —
separate from whatever permissions your local/build-time credentials needed
to push it.

---

## 9. Versioning and rebuilds

- For a first rollout, `latest` is fine. Once this is in regular use,
  consider tagging with a version (e.g. `gedi-processor:v1`,
  `gedi-processor:v2`) so a SageMaker job always references a known-good
  image rather than whatever `latest` happens to point at when someone
  rebuilds.
- Whenever you rebuild after a `Dockerfile.sagemaker-gedi` change, repeat
  steps 3–7. The build-time assertion in step 3 will catch it immediately if
  a routine `pip install` version bump anywhere accidentally drags the
  pinned boto stack along with it.
- Keep `Dockerfile.sagemaker-gedi` and `Dockerfile.sagemaker-lidar` as
  separate images/repos (`gedi-processor` vs. `lidar-processor`) rather than
  merging them — see the rationale documented at the top of
  `Dockerfile.sagemaker-gedi` itself (non-overlapping dependencies, and a
  real risk of the two pipelines' boto stack requirements conflicting if
  resolved together).

---

## Quick command reference (copy-paste block)

```bash
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export AWS_REGION=us-east-1
export REPO_NAME=gedi-processor
export IMAGE_TAG=latest

aws ecr create-repository --repository-name "$REPO_NAME" --region "$AWS_REGION"   # one-time

aws ecr get-login-password --region "$AWS_REGION" \
    | docker login --username AWS --password-stdin "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"

docker build -f Dockerfile.sagemaker-gedi -t "$REPO_NAME:$IMAGE_TAG" .

docker tag "$REPO_NAME:$IMAGE_TAG" "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$REPO_NAME:$IMAGE_TAG"

docker push "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$REPO_NAME:$IMAGE_TAG"

aws ecr describe-images --repository-name "$REPO_NAME" --region "$AWS_REGION" --output table
```
