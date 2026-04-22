# Remote state backend using OCI Object Storage via its S3-compatible API.
#
# Environment-specific values (bucket, endpoint, credentials) are intentionally
# absent from this file. They live in backend.hcl, which is gitignored.
# Copy backend.hcl.example to backend.hcl, populate it, then initialise with:
#
#   terraform init -backend-config=backend.hcl
#
# The flags below are fixed for every OCI deployment and document why this backend
# talks to OCI rather than AWS:
#
#   skip_*                  OCI's S3-compatible API does not expose the AWS metadata,
#                           credential-validation, or STS endpoints that Terraform's
#                           S3 backend probes by default. Disabling these checks is
#                           required — they would fail unconditionally against OCI.
#
#   use_path_style          OCI uses path-style bucket URLs (endpoint/bucket/key),
#                           not virtual-hosted-style (bucket.endpoint/key).
#                           use_path_style is the Terraform 1.6+ name; the older
#                           force_path_style alias was removed in 1.6.
terraform {
  backend "s3" {
    skip_region_validation      = true
    skip_credentials_validation = true
    skip_metadata_api_check     = true
    skip_requesting_account_id  = true
    use_path_style              = true
  }
}
