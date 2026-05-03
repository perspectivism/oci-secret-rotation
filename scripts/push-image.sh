#!/usr/bin/env bash
# Build the rotation Function image and push it to OCIR.
# README.md Quickstart step 4 — run this after configuring terraform.tfvars (step 3)
# and before terraform apply (step 5). Reads region, ocir_repo, and image_tag from terraform.tfvars.
#
# Requires: OCI CLI (configured via oci setup config), Docker, jq

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TFVARS="$SCRIPT_DIR/../infra/terraform.tfvars"
FUNCTION_DIR="$SCRIPT_DIR/../function"

if [[ ! -f "$TFVARS" ]]; then
  echo "Error: $TFVARS not found." >&2
  echo "Copy infra/terraform.tfvars.example to infra/terraform.tfvars and fill in values first." >&2
  exit 1
fi

parse_tfvar() {
  grep "^$1" "$TFVARS" | head -1 | cut -d'"' -f2
}

REGION=$(parse_tfvar region)
OCIR_REPO=$(parse_tfvar ocir_repo)
IMAGE_TAG=$(parse_tfvar image_tag)
COMPARTMENT_OCID=$(parse_tfvar compartment_ocid)

if [[ -z "$REGION" ]]; then
  echo "Error: 'region' not set in $TFVARS" >&2
  exit 1
fi

if [[ -z "$OCIR_REPO" ]]; then
  echo "Error: 'ocir_repo' not set in $TFVARS" >&2
  exit 1
fi

if [[ -z "$IMAGE_TAG" ]]; then
  echo "Error: 'image_tag' not set in $TFVARS" >&2
  exit 1
fi

if [[ -z "$COMPARTMENT_OCID" ]]; then
  echo "Error: 'compartment_ocid' not set in $TFVARS" >&2
  exit 1
fi

NAMESPACE=$(oci os ns get --query 'data' --raw-output)
IMAGE_URL="${REGION}.ocir.io/${NAMESPACE}/${OCIR_REPO}:${IMAGE_TAG}"

echo "Image: $IMAGE_URL"
echo ""

echo "Creating OCIR repository in target compartment (skipped if already exists)..."
oci artifacts container repository create \
  --compartment-id "$COMPARTMENT_OCID" \
  --display-name "$OCIR_REPO" \
  --is-public false 2>/dev/null \
  && echo "Repository created." \
  || echo "Repository already exists, continuing."

echo "Authenticating to OCIR..."
# Obtains a short-lived bearer token via the OCI CLI and pipes it directly to
# docker login so the token is not written to shell history. Docker may still
# persist the login in ~/.docker/config.json, or in an external credential
# store/helper if configured.
# See: https://docs.docker.com/reference/cli/docker/login/#credential-stores
oci raw-request \
  --http-method GET \
  --target-uri "https://${REGION}.ocir.io/20180419/docker/token" \
  | jq -r '.data.access_token' \
  | docker login "${REGION}.ocir.io" -u BEARER_TOKEN --password-stdin

echo "Building..."
docker build -t "$IMAGE_URL" "$FUNCTION_DIR"

echo "Pushing..."
docker push "$IMAGE_URL"

echo ""
echo "Done. Image available at: $IMAGE_URL"
