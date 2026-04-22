#!/usr/bin/env bash
# Cleanly tears down all resources created by terraform apply.
#
# Run from the repo root:
#   bash scripts/destroy.sh
#
# Prerequisites: OCI CLI configured (~/.oci/config), terraform init completed,
# and scripts/set-env.sh sourced (or SECRET_OCID / FUNCTION_ID / NAMESPACE /
# BUCKET_NAME already set in the environment).
#
# Steps performed:
#   1. Disable auto-rotation on the secret (OCI blocks deletion otherwise)
#   2. Empty the target Object Storage bucket (terraform cannot delete a non-empty bucket)
#   3. terraform destroy

set -euo pipefail

INFRA_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../infra" && pwd)"

# Populate environment variables from Terraform outputs if not already set.
if [[ -z "${SECRET_OCID:-}" ]]; then
  echo "Sourcing environment from Terraform outputs..."
  # shellcheck source=scripts/set-env.sh
  source "$(dirname "${BASH_SOURCE[0]}")/set-env.sh"
fi

echo ""
echo "=== Step 1: Disable auto-rotation ==="
echo "OCI will not schedule a secret for deletion while auto-rotation is enabled."
oci vault secret update \
  --secret-id "$SECRET_OCID" \
  --rotation-config "{\"isScheduledRotationEnabled\": false, \"rotationInterval\": \"P30D\", \"targetSystemDetails\": {\"targetSystemType\": \"FUNCTION\", \"functionId\": \"$FUNCTION_ID\"}}"
echo "Auto-rotation disabled."

echo ""
echo "=== Step 2: Empty target bucket ==="
echo "Deleting all objects from bucket: $BUCKET_NAME"
oci os object bulk-delete \
  --namespace "$NAMESPACE" \
  --bucket-name "$BUCKET_NAME" \
  --force
echo "Bucket emptied."

echo ""
echo "=== Step 3: terraform destroy ==="
cd "$INFRA_DIR"
terraform destroy

echo ""
echo "=== Destroy complete ==="
echo ""
echo "Post-destroy reminders:"
echo "  • The Vault secret is in PENDING_DELETION state (30-day retention window)."
echo "    To force deletion sooner:"
echo "    oci vault secret schedule-secret-deletion \\"
echo "      --secret-id \$SECRET_OCID \\"
echo "      --time-of-deletion \$(date -u -d '+1 day' +%Y-%m-%dT%H:%M:%S.000Z)"
echo ""
echo "  • The KMS master key has a soft-delete window. Delete it via:"
echo "    OCI Console → Security → Vault → Keys"
echo ""
echo "  • The OCIR container image is not removed by terraform destroy."
echo "    Delete it with:"
echo "    IMAGE_DIGEST=\$(oci artifacts container image list \\"
echo "      --compartment-id <COMPARTMENT_OCID> \\"
echo "      --repository-name secret-rotation/rotation-handler \\"
echo "      --query 'data.items[0].id' --raw-output)"
echo "    oci artifacts container image delete --image-id \$IMAGE_DIGEST --force"
