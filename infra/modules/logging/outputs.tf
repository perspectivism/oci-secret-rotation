output "log_group_id" {
  description = "OCID of the log group. Passed to the Function application resource so its invocation logs are written here."
  value       = oci_logging_log_group.rotation.id
}

output "notification_topic_id" {
  description = "OCID of the ONS notification topic. Passed to the function config so the rotation handler can publish directly after a successful rotation."
  value       = oci_ons_notification_topic.rotation_events.id
}
