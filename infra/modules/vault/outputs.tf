output "vault_id" {
  description = "OCID of the OCI Vault. Referenced by the secret and by the IAM module when scoping policies."
  value       = oci_kms_vault.vault.id
}

output "vault_management_endpoint" {
  description = "Management endpoint URL for the Vault. Required by any resource that creates or manages keys within this Vault."
  value       = oci_kms_vault.vault.management_endpoint
}

output "key_id" {
  description = "OCID of the AES-256 customer-managed master key. Passed to the secret resource and used to verify encryption configuration."
  value       = oci_kms_key.master_key.id
}

output "secret_id" {
  description = "OCID of the Vault secret. Used by the rotation Function to read and write secret versions, and by the IAM module to scope rotation policies."
  value       = oci_vault_secret.secret.id
}
