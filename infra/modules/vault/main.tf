terraform {
  required_providers {
    oci = {
      source = "oracle/oci"
    }
  }
}

# Creates a DEFAULT (software-protected) OCI Vault.
#
# vault_type = "DEFAULT" uses OCI-managed HSM infrastructure with software key
# protection — no dedicated HSM partition, no fixed monthly HSM cost. Key API
# operations are billed per-use at fractions of a cent.
#
# Upgrading to "VIRTUAL_PRIVATE" provides a dedicated HSM partition with stronger
# non-exportability guarantees but costs significantly more. The rotation
# pattern is identical regardless of vault type; see docs/design.md §5 for the tradeoff.
resource "oci_kms_vault" "vault" {
  compartment_id = var.compartment_id
  display_name   = var.vault_display_name
  vault_type     = "DEFAULT"
}

# Creates an AES-256 customer-managed master key (CMK) within the Vault.
#
# This key encrypts the secret material at rest. Using a customer-managed key
# (rather than an Oracle-managed key) means the key's lifecycle is under our
# control: disabling it immediately blocks decryption; deletion is permanent
# but subject to OCI's minimum retention window.
# protection_mode = "SOFTWARE" matches the DEFAULT vault type.
#
# Scheduled automatic KMS key rotation is available only for keys in
# VIRTUAL_PRIVATE vaults, so it is intentionally not configured here. DEFAULT
# vault keys can be rotated manually by creating a new key version:
# `oci kms management key-version create` (see docs/runbook.md §6).
#
# management_endpoint references the Vault created above, establishing the
# dependency chain: Vault must exist before the key can be created.
resource "oci_kms_key" "master_key" {
  compartment_id      = var.compartment_id
  display_name        = var.key_display_name
  management_endpoint = oci_kms_vault.vault.management_endpoint
  protection_mode     = "SOFTWARE"

  key_shape {
    # AES-256: 32 bytes. Standard for symmetric encryption of secret material.
    algorithm = "AES"
    length    = 32
  }
}

# Creates the secret in the Vault, encrypted with the CMK above.
#
# The initial content is a base64-encoded placeholder. The rotation Function
# will overwrite this with a real credential on the first rotation trigger.
#
# OCI Vault enforces soft-delete on secrets: a deleted secret enters
# PENDING_DELETION state for a configurable retention window (1–30 days)
# before permanent deletion. This provides a recovery path against accidental
# or malicious deletion.
resource "oci_vault_secret" "secret" {
  compartment_id = var.compartment_id
  vault_id       = oci_kms_vault.vault.id
  key_id         = oci_kms_key.master_key.id
  secret_name    = var.secret_name

  secret_content {
    content_type = "BASE64"
    # Placeholder replaced on first rotation — not a real credential.
    content = base64encode("initial-placeholder-replaced-on-first-rotation")
  }

  # rotation_config is omitted on the first apply (function_ocid is empty) to break
  # the vault↔function cycle. The second apply adds it once the real OCID is known.
  dynamic "rotation_config" {
    for_each = var.function_ocid != "" ? [1] : []
    content {
      is_scheduled_rotation_enabled = true
      # ISO 8601 duration — "P30D" means 30 days. Min 1 day, max 360 days.
      rotation_interval = "P${var.rotation_interval_days}D"

      target_system_details {
        target_system_type = "FUNCTION"
        function_id        = var.function_ocid
      }
    }
  }
}
