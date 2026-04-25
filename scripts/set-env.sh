#!/usr/bin/env bash
# Populate shell environment variables from Terraform outputs.
# Source this file from the repo root before running runbook commands:
#
#   source scripts/set-env.sh
#
# Requires: terraform, OCI CLI, jq (for log search output formatting)
# Must be run after `terraform apply` has completed at least once.

set -euo pipefail

INFRA_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../infra" && pwd)"

echo "Reading Terraform outputs from $INFRA_DIR ..."

export SECRET_OCID=$(cd "$INFRA_DIR" && terraform output -raw secret_id)
export FUNCTION_ID=$(cd "$INFRA_DIR" && terraform output -raw function_id)
export VAULT_ID=$(cd "$INFRA_DIR" && terraform output -raw vault_id)
export LOG_GROUP_ID=$(cd "$INFRA_DIR" && terraform output -raw log_group_id)
export NOTIFICATION_TOPIC_ID=$(cd "$INFRA_DIR" && terraform output -raw notification_topic_id)
export BUCKET_NAME=$(cd "$INFRA_DIR" && terraform output -raw bucket_name)
export OBJECT_NAME=$(cd "$INFRA_DIR" && terraform output -raw object_name)
export NAMESPACE=$(cd "$INFRA_DIR" && terraform output -raw namespace)
export COMPARTMENT_OCID=$(cd "$INFRA_DIR" && terraform output -raw compartment_id)
export IMAGE_URL=$(cd "$INFRA_DIR" && terraform output -raw image_url)
export REGION=$(grep '^region' ~/.oci/config | head -1 | cut -d'=' -f2 | tr -d ' ')

echo "Environment ready. Variables set:"
echo "  SECRET_OCID            = $SECRET_OCID"
echo "  FUNCTION_ID            = $FUNCTION_ID"
echo "  VAULT_ID               = $VAULT_ID"
echo "  LOG_GROUP_ID           = $LOG_GROUP_ID"
echo "  NOTIFICATION_TOPIC_ID  = $NOTIFICATION_TOPIC_ID"
echo "  BUCKET_NAME            = $BUCKET_NAME"
echo "  OBJECT_NAME            = $OBJECT_NAME"
echo "  NAMESPACE              = $NAMESPACE"
echo "  COMPARTMENT_OCID       = $COMPARTMENT_OCID"
echo "  IMAGE_URL              = $IMAGE_URL"
echo "  REGION                 = $REGION"
