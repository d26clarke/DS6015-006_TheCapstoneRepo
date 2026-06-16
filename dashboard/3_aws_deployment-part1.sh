#!/bin/bash
# =============================================================================
# 3. AWS CLI Deployment Commands
# =============================================================================
# Run these commands from your local terminal or EC2 instance to deploy
# the compiled React app to S3 and set up the CloudFront CDN.

# ---------------------------------------------------------
# Step A: Create and Configure the Hosting Bucket
# ---------------------------------------------------------
BUCKET_NAME="central-va-tree-canopy-dashboard"
REGION="us-east-1"

# 1. Create the bucket
aws s3api create-bucket \
    --bucket $BUCKET_NAME \
    --region $REGION

# 2. Disable "Block Public Access" (required for static website hosting)
aws s3api put-public-access-block \
    --bucket $BUCKET_NAME \
    --public-access-block-configuration \
      "BlockPublicAcls=false,IgnorePublicAcls=false,BlockPublicPolicy=false,RestrictPublicBuckets=false"

# 3. Enable static website hosting
aws s3 website s3://$BUCKET_NAME/ \
    --index-document index.html \
    --error-document index.html

# 4. Attach a public read policy
aws s3api put-bucket-policy \
    --bucket $BUCKET_NAME \
    --policy '{
      "Version": "2012-10-17",
      "Statement": [{
        "Sid": "PublicReadGetObject",
        "Effect": "Allow",
        "Principal": "*",
        "Action": "s3:GetObject",
        "Resource": "arn:aws:s3:::'$BUCKET_NAME'/*"
      }]
    }'


echo "Deployment part 1 complete! Execute npm run build and Update src/config.ts with the generated domain."
