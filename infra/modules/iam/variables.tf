variable "tenancy_id" {
  description = "OCID of the OCI tenancy root compartment. Required because dynamic groups are tenancy-level resources — they must be created in the root, not in a child compartment."
  type        = string
}

variable "compartment_id" {
  description = "OCID of the application compartment. IAM policies are scoped to this compartment rather than the tenancy root, limiting the blast radius of any policy misconfiguration."
  type        = string
}

variable "function_ocid" {
  description = "OCID of the deployed rotation Function. Used in the dynamic group matching rule so that only this specific Function receives the rotation permissions. Must be updated in M5 once the Function is deployed."
  type        = string
  # Placeholder — the dynamic group rule will not match any real resource until
  # this is replaced with the deployed Function's OCID in M5.
  default = "ocid1.fnfunc.oc1..placeholder-update-in-m5"
}

variable "dynamic_group_name" {
  description = "Name for the IAM dynamic group that the rotation Function is matched into."
  type        = string
  default     = "secret-rotation-function-dg"
}

variable "policy_name" {
  description = "Name for the IAM policy granting the dynamic group and Vault service the permissions required for rotation."
  type        = string
  default     = "secret-rotation-policy"
}
