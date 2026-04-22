# Root module outputs — surfaces the OCIDs and names most useful for
# post-apply verification and for cross-module references in later milestones.

output "vault_id" {
  description = "OCID of the OCI Vault. Use with 'oci vault vault get' to confirm the vault is ACTIVE."
  value       = module.vault.vault_id
}

output "secret_id" {
  description = "OCID of the secret. Use with 'oci secrets secret-bundle get' to retrieve the current version after apply."
  value       = module.vault.secret_id
}

output "vault_management_endpoint" {
  description = "Management endpoint URL for the Vault. Needed for KMS key operations and for any CLI commands that target the Vault directly."
  value       = module.vault.vault_management_endpoint
}

output "key_id" {
  description = "OCID of the AES-256 customer-managed master key."
  value       = module.vault.key_id
}

output "dynamic_group_name" {
  description = "Name of the IAM dynamic group. Used to verify the Function is matched into the group after M4 deployment."
  value       = module.iam.dynamic_group_name
}

output "log_group_id" {
  description = "OCID of the log group. Referenced by the Function application resource in M4."
  value       = module.logging.log_group_id
}

output "notification_topic_id" {
  description = "OCID of the ONS notification topic. Used to add subscriptions and to verify event delivery in M6."
  value       = module.logging.notification_topic_id
}
