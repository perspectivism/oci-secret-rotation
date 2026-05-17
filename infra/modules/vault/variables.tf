variable "compartment_id" {
  description = "OCID of the compartment in which the Vault, KMS key, and secret will be created."
  type        = string
}

variable "vault_display_name" {
  description = "Display name for the OCI Vault resource."
  type        = string
  default     = "secret-rotation-vault"
}

variable "key_display_name" {
  description = "Display name for the KMS master key used to encrypt the secret at rest."
  type        = string
  default     = "secret-rotation-key"
}

variable "secret_name" {
  description = "Name of the secret within the Vault. Must be unique within the compartment."
  type        = string
}

variable "function_ocid" {
  description = "OCID of the rotation Function. Wired from the function module output — used to configure the rotation_config scheduler on the secret."
  type        = string
}

variable "rotation_interval_days" {
  description = "Number of days between automatic rotations. Rendered as an ISO 8601 duration (P<n>D) in the rotation_config block."
  type        = number
  default     = 30
}
