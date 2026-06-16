#!/bin/bash
# =============================================================================
# 3. AWS CLI Deployment Commands Part 2
# =============================================================================
# Run these commands from your local terminal or EC2 instance to deploy
# the compiled React app to S3 and set up the CloudFront CDN.
BUCKET_NAME="central-va-tree-canopy-dashboard"
REGION="us-east-1"
 
# ---------------------------------------------------------
# Step B: Sync the React App Build to S3
# ---------------------------------------------------------
# At this point, you have run `npm run build` in your React project first.
# Run this from the root of your React project.

# Sync the assets with a 1-year cache
aws s3 sync dist/ s3://$BUCKET_NAME/ \
    --delete \
    --cache-control "max-age=31536000,immutable"

# Overwrite index.html with a no-cache header so updates are immediate
aws s3 cp dist/index.html s3://$BUCKET_NAME/index.html \
    --cache-control "no-cache,no-store,must-revalidate" \
    --content-type "text/html"

# ---------------------------------------------------------
# Step C: Set CORS on the Data Bucket
# ---------------------------------------------------------
# The React app needs to fetch JSON from the central data bucket.

aws s3api put-bucket-cors \
    --bucket $BUCKET_NAME \
    --cors-configuration '{
      "CORSRules": [{
        "AllowedOrigins": ["*"],
        "AllowedMethods": ["GET"],
        "AllowedHeaders": ["*"],
        "MaxAgeSeconds": 3600
      }]
    }'

# ---------------------------------------------------------
# Step D: Create the CloudFront Distribution
# ---------------------------------------------------------
# This creates a CDN endpoint that points to your S3 website.

aws cloudfront create-distribution \
    --distribution-config '{
      "CallerReference": "central-virginia-tree-canopy-'$(date +%s)'",
      "Origins": {
        "Quantity": 1,
        "Items": [{
          "Id": "S3-'$BUCKET_NAME'",
          "DomainName": "'$BUCKET_NAME'.s3-website-'$REGION'.amazonaws.com",
          "CustomOriginConfig": {
            "HTTPPort": 80,
            "HTTPSPort": 443,
            "OriginProtocolPolicy": "http-only"
          }
        }]
      },
      "DefaultCacheBehavior": {
        "TargetOriginId": "S3-'$BUCKET_NAME'",
        "ViewerProtocolPolicy": "redirect-to-https",
        "CachePolicyId": "658327ea-f89d-4fab-a63d-7e88639e58f6",
        "Compress": true
      },
      "CustomErrorResponses": {
        "Quantity": 1,
        "Items": [{
          "ErrorCode": 404,
          "ResponsePagePath": "/index.html",
          "ResponseCode": "200",
          "ErrorCachingMinTTL": 0
        }]
      },
      "Comment": "Central Virginia Tree Canopy Dashboard",
      "Enabled": true,
      "HttpVersion": "http2"
    }'

# ---------------------------------------------------------
# Step E: Retrieve the Public URL
# ---------------------------------------------------------
echo "Retrieving your public CloudFront URL..."
aws cloudfront list-distributions \
    --query "DistributionList.Items[?Comment=='Central Virginia Tree Canopy Dashboard'].DomainName" \
    --output text

echo "Deployment Paert 2 complete! Update src/config.ts with the generated domain above, rebuild, and re-sync."
