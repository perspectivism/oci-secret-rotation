output "dynamic_group_id" {
  description = "OCID of the rotation Function dynamic group. Can be used to verify Function group membership after deployment."
  value       = oci_identity_dynamic_group.rotation_function.id
}

output "dynamic_group_name" {
  description = "Name of the rotation Function dynamic group. Returned for reference; the policy references it directly via resource interpolation."
  value       = oci_identity_dynamic_group.rotation_function.name
}

output "vault_secret_dynamic_group_id" {
  description = "OCID of the rotation Vault Secret dynamic group. Can be used to verify secret group membership after deployment."
  value       = oci_identity_dynamic_group.rotation_secret.id
}

output "vault_secret_dynamic_group_name" {
  description = "Name of the rotation Vault Secret dynamic group. Returned for reference."
  value       = oci_identity_dynamic_group.rotation_secret.name
}

output "policy_id" {
  description = "OCID of the rotation IAM policy."
  value       = oci_identity_policy.rotation.id
}
