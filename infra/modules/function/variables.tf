variable "compartment_id" {
  description = "OCID of the compartment in which the Function application, function, and OCIR repository are created."
  type        = string
}

variable "subnet_id" {
  description = "OCID of the private subnet the Function application is attached to. Sourced from the network module."
  type        = string
}

variable "secret_id" {
  description = "OCID of the Vault secret the function will rotate. Injected as SECRET_OCID in the function application config map."
  type        = string
}

variable "log_group_id" {
  description = "OCID of the log group to write function invocation service logs into. Sourced from the logging module."
  type        = string
}

variable "tenancy_namespace" {
  description = "OCI Object Storage namespace for the tenancy. Used to construct the OCIR image URL. Derived via oci_objectstorage_namespace data source at the root level."
  type        = string
}

variable "region" {
  description = "OCI region identifier (e.g. us-chicago-1). Used to construct the OCIR registry hostname."
  type        = string
}

variable "ocir_repo" {
  description = "OCIR repository path (e.g. secret-rotation/rotation-handler). The container repository is created with this name."
  type        = string
  default     = "secret-rotation/rotation-handler"
}

variable "image_tag" {
  description = "Tag of the container image to deploy. Override in terraform.tfvars when deploying a specific build."
  type        = string
  default     = "latest"
}

variable "target_bucket_name" {
  description = "Name of the Object Storage bucket the function writes the rotated credential to. Injected as TARGET_BUCKET in the function config."
  type        = string
}

variable "target_namespace" {
  description = "Object Storage namespace. Injected as TARGET_NAMESPACE in the function config."
  type        = string
}

variable "target_object_name" {
  description = "Object name within the target bucket. Injected as TARGET_OBJECT in the function config."
  type        = string
}
