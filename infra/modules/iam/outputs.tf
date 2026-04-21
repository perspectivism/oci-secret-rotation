output "dynamic_group_id" {
  description = "OCID of the dynamic group. Can be used to verify group membership after Function deployment."
  value       = oci_identity_dynamic_group.rotation_function.id
}

output "dynamic_group_name" {
  description = "Name of the dynamic group. Returned for reference; the policy references it directly via resource interpolation."
  value       = oci_identity_dynamic_group.rotation_function.name
}

output "policy_id" {
  description = "OCID of the rotation IAM policy."
  value       = oci_identity_policy.rotation.id
}
