variable "compartment_id" {
  description = "OCID of the compartment in which all logging resources will be created."
  type        = string
}

variable "log_group_display_name" {
  description = "Display name for the OCI log group that contains all rotation-related logs."
  type        = string
  default     = "secret-rotation-demo-logs"
}

variable "notification_topic_name" {
  description = "Name for the ONS topic that receives secret rotation events. Must be unique within the compartment."
  type        = string
  default     = "secret-rotation-events"
}

variable "notification_endpoint" {
  description = "Email address or HTTPS URL that receives rotation event notifications via the ONS subscription. Set before enabling the events rule in M6."
  type        = string
  default     = "placeholder@example.com"
}

variable "events_rule_name" {
  description = "Display name for the Events rule that fires on secret version creation."
  type        = string
  default     = "secret-version-created-rule"
}
