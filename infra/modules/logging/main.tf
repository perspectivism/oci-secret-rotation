# Log group that contains all rotation-related logs.
#
# A dedicated log group keeps rotation logs isolated from other application
# logs in the compartment, making log search queries and access control simpler.
resource "oci_logging_log_group" "rotation" {
  compartment_id = var.compartment_id
  display_name   = var.log_group_display_name
  description    = "Contains structured logs emitted by the secret rotation Function."
}

# ONS (Oracle Notification Service) topic that receives rotation completion notifications.
#
# The rotation Function publishes directly to this topic after each successful rotation.
# OCI Events Service does not expose secret version creation events, so direct publish
# from the Function is used instead. Decoupling the topic from the subscription means
# multiple consumers can subscribe without changing the Function or Vault configuration.
resource "oci_ons_notification_topic" "rotation_events" {
  compartment_id = var.compartment_id
  name           = var.notification_topic_name
  description    = "Receives rotation completion notifications published directly by the rotation Function."
}

# ONS subscription that delivers rotation notifications to the configured endpoint.
#
# protocol = "EMAIL" delivers a human-readable notification for each rotation.
# For HTTPS delivery (e.g. PagerDuty, Slack webhook), change protocol to
# "HTTPS" and set notification_endpoint accordingly.
# The subscription confirmation email must be acknowledged before delivery begins.
resource "oci_ons_subscription" "rotation_events" {
  compartment_id = var.compartment_id
  topic_id       = oci_ons_notification_topic.rotation_events.id
  protocol       = "EMAIL"
  endpoint       = var.notification_endpoint
}

