To build the required lambda layer

If Building on Apple Silicon (M1/M2/M3 Mac)

If you are building on an Apple Silicon Mac, Docker may be building for linux/arm64 by default, which can cause wheel resolution mismatches. Force the build to target the Lambda execution platform explicitly:

Run docker build --no-cache --platform linux/amd64 -t tree-canopy-lambda-layer .

Or add the platform declaration directly in the Dockerfile:

FROM --platform=linux/amd64 public.ecr.aws/lambda/python:3.11

For Non MACs
Run docker build --platform linux/arm64 -t tree-canopy-lambda-layer .


(Optional) Use `docker cp` to extract the .zip to your local machine
docker cp <container_id>:/opt/layer.zip .

In this case, my docker container_id is 


Upload the zip file into the tree-canopy-api-backend lambda function
