output "bucket_name" {
  description = "Name of the Object Storage bucket. Passed to the function config as TARGET_BUCKET and to the IAM module for the bucket-scoped policy."
  value       = oci_objectstorage_bucket.target.name
}

output "namespace" {
  description = "Object Storage namespace. Passed to the function config as TARGET_NAMESPACE."
  value       = oci_objectstorage_bucket.target.namespace
}

output "object_name" {
  description = "Object name within the bucket. Passed to the function config as TARGET_OBJECT."
  value       = var.object_name
}
