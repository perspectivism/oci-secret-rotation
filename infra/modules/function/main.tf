locals {
  image_url = "${var.region}.ocir.io/${var.tenancy_namespace}/${var.ocir_repo}:${var.image_tag}"
}

# Private OCIR repository that holds the rotation Function image.
# is_public = false ensures only authenticated principals with the correct IAM
# policy can pull the image — the Functions service pulls it using its own
# service principal when the function is invoked.
resource "oci_artifacts_container_repository" "rotation" {
  compartment_id = var.compartment_id
  display_name   = var.ocir_repo
  is_public      = false
}

# Function application — the logical container for one or more functions sharing
# the same network placement, config, and logging policy.
# subnet_ids attaches the application to the private subnet created by the
# network module; all function VNICs are provisioned there.
# config injects SECRET_OCID so the handler can read the target secret without
# any hardcoded values in the image.
resource "oci_functions_application" "rotation" {
  compartment_id = var.compartment_id
  display_name   = "secret-rotation-app"
  subnet_ids     = [var.subnet_id]

  config = {
    SECRET_OCID      = var.secret_id
    TARGET_BUCKET    = var.target_bucket_name
    TARGET_NAMESPACE = var.target_namespace
    TARGET_OBJECT    = var.target_object_name
    ONS_TOPIC_ID     = var.notification_topic_id
  }
}

# The deployed function. memory_in_mbs and timeout_in_seconds match func.yaml
# so the Terraform resource and the Fn project manifest stay in sync.
# The image reference is constructed from the OCIR repo created above — push
# the image before invoking, but Terraform apply can proceed before the push.
resource "oci_functions_function" "rotation" {
  application_id     = oci_functions_application.rotation.id
  display_name       = "secret-rotation-handler"
  image              = local.image_url
  memory_in_mbs      = 256
  timeout_in_seconds = 120

  depends_on = [oci_artifacts_container_repository.rotation]
}

# Service log that captures function invocation events (start, result, duration)
# for every call to the rotation function. Written into the shared log group
# created by the logging module.
resource "oci_logging_log" "function_invocation" {
  display_name       = "secret-rotation-invocation-log"
  log_group_id       = var.log_group_id
  log_type           = "SERVICE"
  is_enabled         = true
  retention_duration = 30

  configuration {
    compartment_id = var.compartment_id

    source {
      category    = "invoke"
      resource    = oci_functions_application.rotation.id
      service     = "functions"
      source_type = "OCISERVICE"
    }
  }
}
