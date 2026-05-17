#!/usr/bin/env bash
# Cleanly tears down all resources created by terraform apply.
#
# Run from the repo root:
#   bash scripts/destroy.sh
#
# Prerequisites: OCI CLI configured (~/.oci/config), terraform init completed,
# and scripts/set-env.sh sourced (or SECRET_ID / FUNCTION_ID / VAULT_ID /
# COMPARTMENT_ID / NAMESPACE / BUCKET_NAME already set in the environment).
#
# Steps performed:
#   1. Prepare and schedule secret deletion (disable auto-rotation, schedule 2-day
#      deletion, remove from Terraform state)
#   2. Schedule vault deletion (8-day window, cascade to keys, remove from state)
#   3. Delete the OCIR container repository — not managed by Terraform, so must
#      be cleaned up explicitly
#   4. Empty the target Object Storage bucket (Terraform cannot delete a non-empty bucket)
#   5. terraform destroy

set -euo pipefail

INFRA_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../infra" && pwd)"

# Populate environment variables from Terraform outputs if not already set.
if [[ -z "${SECRET_ID:-}" ]]; then
  echo "Sourcing environment from Terraform outputs..."
  # shellcheck source=scripts/set-env.sh
  source "$(dirname "${BASH_SOURCE[0]}")/set-env.sh"
fi

echo ""
echo "=== Step 1: Prepare and schedule secret deletion ==="
# Auto-rotation must be disabled before OCI will allow the secret to be scheduled
# for deletion. Skip if FUNCTION_ID is empty — rotation_config was never applied
# (first-apply-only deployment), so there is nothing to disable.
if [[ -z "${FUNCTION_ID:-}" ]]; then
  echo "FUNCTION_ID not set — rotation was not configured, skipping disable step."
else
  echo "Disabling auto-rotation..."
  oci vault secret update \
    --secret-id "$SECRET_ID" \
    --rotation-config "{\"isScheduledRotationEnabled\": false, \"rotationInterval\": \"P30D\", \"targetSystemDetails\": {\"targetSystemType\": \"FUNCTION\", \"functionId\": \"$FUNCTION_ID\"}}"
  echo "Auto-rotation disabled."
fi

# Schedule the secret for deletion before terraform destroy runs. This moves the
# secret to PENDING_DELETION immediately, which prevents terraform destroy from
# hanging — Terraform sees the resource is already being removed and skips the
# delete wait. A 2-day window is used to stay safely above OCI's minimum; the
# secret is permanently deleted ~48 hours later.
echo "Scheduling secret for deletion (2-day retention window)..."
oci vault secret schedule-secret-deletion \
  --secret-id "$SECRET_ID" \
  --time-of-deletion "$(date -u -d '+2 days' +%Y-%m-%dT%H:%M:%S.000Z)"
echo "Secret scheduled for deletion — permanently removed in ~48 hours."

# Remove the secret from Terraform state so terraform destroy does not try to
# delete it again. The OCI provider waits for DELETED state, which won't arrive
# for ~48 hours — terraform destroy would hang or error with 409-IncorrectState.
# Dropping it from state lets the OCI-side scheduled deletion handle the cleanup.
cd "$INFRA_DIR"
terraform state rm module.vault.oci_vault_secret.secret
echo "Secret removed from Terraform state."

echo ""
echo "=== Step 2: Schedule vault deletion ==="
# Schedule vault deletion at 8 days — one day above OCI's 7-day minimum to
# avoid boundary check errors. Scheduling the vault also cascades to all keys
# within it, so no separate key scheduling command is needed.
echo "Scheduling vault for deletion (8-day window)..."
oci kms management vault schedule-deletion \
  --vault-id "$VAULT_ID" \
  --time-of-deletion "$(date -u -d '+8 days' +%Y-%m-%dT%H:%M:%S.000Z)"
echo "Vault scheduled for deletion — permanently removed in ~8 days."

# Remove vault and key from Terraform state so terraform destroy does not
# try to delete them again and conflict with their PENDING_DELETION state.
cd "$INFRA_DIR"
terraform state rm module.vault.oci_kms_key.master_key
terraform state rm module.vault.oci_kms_vault.vault
echo "Vault and key removed from Terraform state."

echo ""
echo "=== Step 3: Delete OCIR container repository ==="
OCIR_REPO=$(grep "^ocir_repo" "$INFRA_DIR/terraform.tfvars" | head -1 | cut -d'"' -f2)
REPO_ID=$(oci artifacts container repository list \
  --compartment-id "$COMPARTMENT_ID" \
  --display-name "$OCIR_REPO" \
  --query 'data.items[0].id' \
  --raw-output 2>/dev/null)
if [[ -n "$REPO_ID" && "$REPO_ID" != "null" ]]; then
  oci artifacts container repository delete \
    --repository-id "$REPO_ID" \
    --force
  echo "Container repository deleted."
else
  echo "Container repository not found, skipping."
fi

echo ""
echo "=== Step 4: Empty target bucket ==="
echo "Deleting all objects from bucket: $BUCKET_NAME"
oci os object bulk-delete \
  --namespace "$NAMESPACE" \
  --bucket-name "$BUCKET_NAME" \
  --force
echo "Bucket emptied."

echo ""
echo "=== Step 5: terraform destroy ==="
cd "$INFRA_DIR"
terraform destroy

echo ""
echo "=== Destroy complete ==="
echo ""
echo "Post-destroy reminders:"
echo "  • The Vault secret is in PENDING_DELETION state — it was scheduled for"
echo "    deletion above with a 2-day window. It will be permanently removed"
echo "    in ~48 hours. No further action needed."
echo ""
echo "  • The KMS Vault and its keys are in PENDING_DELETION state — they"
echo "    were scheduled above with an 8-day window and will be permanently"
echo "    removed ~8 days after this script ran."
