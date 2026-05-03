#!/usr/bin/env bash
# Populate shell environment variables from Terraform outputs.
# Source this file from the repo root before running runbook commands:
#
#   source scripts/set-env.sh
#
# Requires: terraform, jq
# Must be run after `terraform apply` has completed at least once.

set -euo pipefail

INFRA_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../infra" && pwd)"

echo "Reading Terraform outputs from $INFRA_DIR ..."

_tf_outputs=$(cd "$INFRA_DIR" && terraform output -json)

_get() { printf '%s' "$_tf_outputs" | jq -r ".$1.value"; }

export SECRET_OCID=$(            _get secret_id)
export FUNCTION_ID=$(            _get function_id)
export VAULT_ID=$(               _get vault_id)
export LOG_GROUP_ID=$(           _get log_group_id)
export NOTIFICATION_TOPIC_ID=$(  _get notification_topic_id)
export BUCKET_NAME=$(            _get bucket_name)
export OBJECT_NAME=$(            _get object_name)
export NAMESPACE=$(              _get namespace)
export COMPARTMENT_OCID=$(       _get compartment_id)
export IMAGE_URL=$(              _get image_url)
export REGION=$(                 _get region)

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
