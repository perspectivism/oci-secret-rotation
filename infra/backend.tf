# Remote state backend using the OCI native backend type.
#
# Requires Terraform >= 1.14. Uses ~/.oci/config for authentication —
# the same credentials as the OCI provider. No Customer Secret Keys, no
# S3-compatible API, no separate service user required.
#
# Environment-specific values (bucket, namespace, region, key) live in
# backend.hcl, which is gitignored. Copy backend.hcl.example to backend.hcl,
# populate it, then initialise with:
#
#   cd infra
#   terraform init -backend-config=backend.hcl
#
# State locking is supported natively via OCI Object Storage conditional writes.
terraform {
  backend "oci" {
    # Auth reads from the DEFAULT profile in ~/.oci/config.
    # No credentials are stored in this file or in backend.hcl.
    config_file_profile = "DEFAULT"
  }
}
