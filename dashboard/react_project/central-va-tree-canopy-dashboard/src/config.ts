const DATA_BASE_URL =
  import.meta.env.PROD
    ? "https://dqs7zvzytpj1t.cloudfront.net/data"  //  replace with the generated cloudfront domain after executing 3_aws_deployment.sh
    : "/data";                                          // local dev fallback

export default DATA_BASE_URL;