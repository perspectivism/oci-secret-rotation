# Input variables for the root module.
# All OCIDs and region values flow through here — nothing is hardcoded in resources.
# Copy terraform.tfvars.example to terraform.tfvars and populate it before running
# terraform plan or apply. terraform.tfvars is gitignored.

variable "tenancy_ocid" {
  description = "OCID of the OCI tenancy in which all resources will be created."
  type        = string
}

variable "user_ocid" {
  description = "OCID of the IAM user whose API key is configured in ~/.oci/config and used for Terraform authentication."
  type        = string
}

variable "region" {
  description = "OCI region identifier (e.g. us-ashburn-1) where all resources will be deployed. Must match the region in ~/.oci/config."
  type        = string
}

variable "compartment_ocid" {
  description = "OCID of the compartment in which all resources will be created. All IAM policies are scoped to this compartment rather than the tenancy root, limiting blast radius."
  type        = string
}

variable "secret_name" {
  description = "Display name for the secret in OCI Vault. Used to identify the secret in console and CLI output."
  type        = string
  default     = "rotation-demo-secret"
}

variable "rotation_interval_days" {
  description = "Number of days between automatic secret rotations. Passed to the Vault secret's rotation_config block — the native Vault scheduler drives rotation on this cadence."
  type        = number
  default     = 30
}
