#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# build_and_push_sagemaker.sh
#
# Builds the custom SageMaker LiDAR processing Docker image and pushes it
# to Amazon ECR in the current AWS account and region.
#
# Prerequisites:
#   - Docker daemon running
#   - AWS CLI configured with credentials that have ECR push permissions
#   - Sufficient IAM permissions:
#       ecr:CreateRepository, ecr:GetAuthorizationToken,
#       ecr:BatchCheckLayerAvailability, ecr:PutImage,
#       ecr:InitiateLayerUpload, ecr:UploadLayerPart,
#       ecr:CompleteLayerUpload
#
# Usage:
#   chmod +x build_and_push_sagemaker.sh
#   ./build_and_push_sagemaker.sh
#
# After a successful push, copy the printed IMAGE_URI into launch_sagemaker_job.py
# ══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

# Configuration
IMAGE_NAME="lidar-processor"
IMAGE_TAG="latest"
DOCKERFILE="Dockerfile.sagemaker-lidar"

# Resolve account ID and region dynamically from the current AWS CLI profile
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION=$(aws configure get region)
REGION=${REGION:-us-east-1}   # fall back to us-east-1 if not set

ECR_REGISTRY="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
FULL_IMAGE_URI="${ECR_REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}"

echo "============================================================"
echo "  SageMaker LiDAR Image Build & Push"
echo "============================================================"
echo "  Account  : ${ACCOUNT_ID}"
echo "  Region   : ${REGION}"
echo "  Image    : ${FULL_IMAGE_URI}"
echo "  Dockerfile: ${DOCKERFILE}"
echo "============================================================"

# Step 1: Authenticate Docker to ECR
echo ""
echo "[1/4] Authenticating Docker to ECR..."
aws ecr get-login-password --region "${REGION}" | \
    docker login --username AWS --password-stdin "${ECR_REGISTRY}"

# Step 2: Authenticate to the AWS public ECR (for base image pull)
# The base image (sagemaker-scikit-learn) lives in the AWS-managed public ECR.
# A separate authentication step is required for public.ecr.aws pulls.
echo ""
echo "[2/4] Authenticating to AWS public ECR (base image registry)..."
aws ecr get-login-password --region us-east-1 | \
    docker login --username AWS --password-stdin \
    683313688378.dkr.ecr.us-east-1.amazonaws.com

# Step 3: Create ECR repository if it does not already exist
echo ""
echo "[3/4] Ensuring ECR repository '${IMAGE_NAME}' exists..."
aws ecr describe-repositories \
    --repository-names "${IMAGE_NAME}" \
    --region "${REGION}" > /dev/null 2>&1 || \
aws ecr create-repository \
    --repository-name "${IMAGE_NAME}" \
    --region "${REGION}" \
    --image-scanning-configuration scanOnPush=true \
    --tags Key=Project,Value=CentralVATreeCanopy \
    --output table

# Step 4: Build and push
echo ""
echo "[4/4] Building Docker image (this takes 5–10 minutes on first build)..."
docker build \
    --platform linux/amd64 \
    --file "${DOCKERFILE}" \
    --tag "${IMAGE_NAME}:${IMAGE_TAG}" \
    --tag "${FULL_IMAGE_URI}" \
    .

echo ""
echo "Pushing image to ECR..."
docker push "${FULL_IMAGE_URI}"

# Done
echo ""
echo "============================================================"
echo "  Build and push complete."
echo "============================================================"
echo ""
echo "  IMAGE_URI = ${FULL_IMAGE_URI}"
echo ""
echo "  Update launch_sagemaker_job.py:"
echo "    Replace the image_uri line with:"
echo "    image_uri = \"${FULL_IMAGE_URI}\""
echo "============================================================"
