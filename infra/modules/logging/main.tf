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

# Custom log that receives structured JSON output from the rotation Function.
#
# log_type = "CUSTOM" means the log is written to programmatically (via the
# OCI Logging ingestion API or the Functions runtime). This is distinct from
# SERVICE logs, which are emitted automatically by OCI services.
# The Function application resource (modules/function/) references this log's
# OCID in its logging_policy block — that association is made in M3/M4.
resource "oci_logging_log" "function_log" {
  display_name = var.function_log_display_name
  log_group_id = oci_logging_log_group.rotation.id
  log_type     = "CUSTOM"
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

# Events rule that fires when OCI Vault creates a new secret version.
#
# is_enabled = false keeps this rule inactive until the full rotation flow is
# verified end-to-end in M6. Enabling a rule before the Function and Vault are
# wired together would produce spurious notifications on every manual secret
# operation during development.
#
# The condition matches the canonical secret version creation event type.
# It can be narrowed in M6 to filter by specific secret OCID if needed
# (add a data.additionalDetails.secretId condition).
resource "oci_events_rule" "secret_version_created" {
  compartment_id = var.compartment_id
  display_name   = var.events_rule_name
  description    = "Publishes to the rotation events topic whenever a new secret version is created. Enabled in M6."
  is_enabled     = false

  condition = jsonencode({
    eventType = ["com.oraclecloud.vaultsecret.createsecretversion"]
    data      = {}
  })

  actions {
    actions {
      # ONS action publishes the event payload to the notification topic.
      # is_enabled mirrors the rule-level flag so no notifications fire
      # until M6 explicitly enables both.
      action_type = "ONS"
      is_enabled  = false
      topic_id    = oci_ons_notification_topic.rotation_events.id
    }
  }
}
