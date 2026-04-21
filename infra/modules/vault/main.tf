# Creates a DEFAULT (software-protected) OCI Vault.
#
# vault_type = "DEFAULT" uses OCI-managed HSM infrastructure with software key
# protection — no dedicated HSM partition, no fixed monthly HSM cost. Key API
# operations are billed per-use at fractions of a cent.
#
# Upgrading to "VIRTUAL_PRIVATE" provides a dedicated HSM partition with stronger
# non-exportability guarantees but costs ~$1,000+/month. The rotation pattern is
# identical regardless of vault type; see docs/design.md §5 for the tradeoff.
resource "oci_kms_vault" "vault" {
  compartment_id = var.compartment_id
  display_name   = var.vault_display_name
  vault_type     = "DEFAULT"
}

# Creates an AES-256 customer-managed master key (CMK) within the Vault.
#
# This key encrypts the secret material at rest. Using a customer-managed key
# (rather than an Oracle-managed key) means the key's lifecycle is under our
# control: we can disable or delete it to immediately revoke access to all
# secrets it protects. protection_mode = "SOFTWARE" matches the DEFAULT vault type.
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
# rotation_config is intentionally absent here. It requires the deployed
# Function's OCID, which is not available until M4. It will be added to this
# resource in M5 when the full rotation wiring is completed.
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
}
