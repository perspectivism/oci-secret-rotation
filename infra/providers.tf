# Declares the Terraform version constraint and the OCI provider source and version pin.
# Pinning to ~> 8.10 allows patch-level updates within the 8.x minor series while
# preventing unexpected breaking changes from a major or minor version bump.
terraform {
  required_version = ">= 1.5"

  required_providers {
    oci = {
      source  = "oracle/oci"
      version = "~> 8.10"
    }
  }
}

# Configures the OCI provider for API key authentication.
# tenancy_ocid, user_ocid, and region are supplied via variables so the deployment
# is fully driven by terraform.tfvars with no hardcoded values here.
# fingerprint and private_key_path are intentionally omitted — the provider reads
# them from ~/.oci/config, keeping credential material out of the repo entirely.
provider "oci" {
  tenancy_ocid = var.tenancy_ocid
  user_ocid    = var.user_ocid
  region       = var.region
}
