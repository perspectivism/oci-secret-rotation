variable "tenancy_id" {
  description = "OCID of the OCI tenancy root compartment. Required because dynamic groups are tenancy-level resources — they must be created in the root, not in a child compartment."
  type        = string
}

variable "compartment_id" {
  description = "OCID of the application compartment. IAM policies are scoped to this compartment rather than the tenancy root, limiting the blast radius of any policy misconfiguration."
  type        = string
}

variable "function_ocid" {
  description = "OCID of the deployed rotation Function. Used in the dynamic group matching rule so that only this specific Function receives the rotation permissions."
  type        = string
}

variable "secret_id" {
  description = "OCID of the rotation Vault Secret. Used in the vault secret dynamic group matching rule and to scope the manage secret-family policy to this single secret."
  type        = string
}

variable "dynamic_group_name" {
  description = "Name for the IAM dynamic group that the rotation Function is matched into."
  type        = string
  default     = "secret-rotation-function-dg"
}

variable "vault_secret_dynamic_group_name" {
  description = "Name for the IAM dynamic group that the rotation Vault Secret is matched into. This group is granted permission to invoke the rotation Function on schedule."
  type        = string
  default     = "secret-rotation-secret-dg"
}

variable "policy_name" {
  description = "Name for the IAM policy granting the two dynamic groups the permissions required for rotation."
  type        = string
  default     = "secret-rotation-policy"
}

variable "target_bucket_name" {
  description = "Name of the Object Storage bucket used as the rotation target. Used to scope the object-write policy to this bucket only."
  type        = string
}

