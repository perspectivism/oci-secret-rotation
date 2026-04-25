output "function_id" {
  description = "OCID of the deployed rotation function. Used in the IAM dynamic group matching rule to scope rotation permissions to this specific function."
  value       = oci_functions_function.rotation.id
}

output "application_id" {
  description = "OCID of the Function application."
  value       = oci_functions_application.rotation.id
}

output "image_url" {
  description = "Full OCIR image URL used by the function. Use this as the target for docker tag and docker push."
  value       = local.image_url
}
