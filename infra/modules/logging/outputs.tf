output "log_group_id" {
  description = "OCID of the log group. Passed to the Function application resource so its invocation logs are written here."
  value       = oci_logging_log_group.rotation.id
}

output "notification_topic_id" {
  description = "OCID of the ONS notification topic. Can be used to add additional subscriptions without modifying the Events rule."
  value       = oci_ons_notification_topic.rotation_events.id
}

output "events_rule_id" {
  description = "OCID of the Events rule. Referenced in M6 when the rule is enabled and the condition is optionally narrowed to a specific secret OCID."
  value       = oci_events_rule.secret_version_created.id
}
