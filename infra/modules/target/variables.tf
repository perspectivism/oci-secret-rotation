variable "compartment_id" {
  description = "OCID of the compartment in which the Object Storage bucket is created."
  type        = string
}

variable "namespace" {
  description = "OCI Object Storage namespace for the tenancy. Derived via oci_objectstorage_namespace at the root level."
  type        = string
}

variable "bucket_name" {
  description = "Name of the Object Storage bucket used as the rotation target. Must be unique within the namespace."
  type        = string
  default     = "secret-rotation-target"
}

variable "object_name" {
  description = "Name of the object within the bucket that stores the current credential value. The rotation function overwrites this object on every rotation."
  type        = string
  default     = "current-credential"
}
