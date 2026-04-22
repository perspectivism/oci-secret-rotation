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

variable "secret_name" {
  description = "Name of the secret the rotation Function is permitted to manage. Narrows the manage secret-family policy to this single named secret rather than all secrets in the compartment."
  type        = string
}

variable "target_bucket_name" {
  description = "Name of the Object Storage bucket used as the rotation target. Used to scope the object-write policy to this bucket only."
  type        = string
}

variable "notification_topic_id" {
  description = "OCID of the ONS topic the function publishes to after rotation. Used to scope the ONS publish policy to this topic only."
  type        = string
}
