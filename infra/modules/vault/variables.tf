variable "compartment_id" {
  description = "OCID of the compartment in which the Vault, KMS key, and secret will be created."
  type        = string
}

variable "vault_display_name" {
  description = "Display name for the OCI Vault resource."
  type        = string
  default     = "secret-rotation-demo-vault"
}

variable "key_display_name" {
  description = "Display name for the KMS master key used to encrypt the secret at rest."
  type        = string
  default     = "secret-rotation-demo-key"
}

variable "secret_name" {
  description = "Name of the secret within the Vault. Must be unique within the compartment."
  type        = string
}
