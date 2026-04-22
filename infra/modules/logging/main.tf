# Log group that contains all rotation-related logs.
#
# A dedicated log group keeps rotation logs isolated from other application
# logs in the compartment, making log search queries and access control simpler.
# The Function application is configured to write to this group in M3/M4.
resource "oci_logging_log_group" "rotation" {
  compartment_id = var.compartment_id
  display_name   = var.log_group_display_name
  description    = "Contains structured logs emitted by the secret rotation Function."
}

# ONS (Oracle Notification Service) topic that receives secret rotation events.
#
# The Events rule below publishes to this topic; subscribers (email, HTTPS, etc.)
# receive a message for each rotation event. Decoupling the topic from the
# subscription means multiple consumers can subscribe without changing the Events
# rule or the Vault configuration.
resource "oci_ons_notification_topic" "rotation_events" {
  compartment_id = var.compartment_id
  name           = var.notification_topic_name
  description    = "Receives com.oraclecloud.vaultsecret.createsecretversion events for alerting and audit."
}

# ONS subscription that delivers rotation events to the configured endpoint.
#
# protocol = "EMAIL" delivers a human-readable notification for each event.
# For HTTPS delivery (e.g. PagerDuty, Slack webhook), change protocol to
# "HTTPS" and set notification_endpoint accordingly.
# The subscription confirmation email must be acknowledged before delivery begins.
# Full verification is done in M6.
resource "oci_ons_subscription" "rotation_events" {
  compartment_id = var.compartment_id
  topic_id       = oci_ons_notification_topic.rotation_events.id
  protocol       = "EMAIL"
  endpoint       = var.notification_endpoint
}

