# OCI Secret Rotation — Runbook

Operational procedures for the secret rotation system. Commands assume environment
variables have been populated by `scripts/set-env.sh`.

---

## Prerequisites

Source the environment script once per shell session before running any commands below:

```bash
source scripts/set-env.sh
```

This calls `terraform output -json` once and uses `jq` to export the values as shell variables. Requires Terraform state to be initialised and a successful `terraform apply`.

---

## Contents

1. [Trigger Secret Rotation Manually](#1-trigger-secret-rotation-manually)
2. [Investigate a Failure](#2-investigate-a-failure)
3. [Rollback to Previous Version](#3-rollback-to-previous-version)
4. [Secret Version Pruning](#4-secret-version-pruning)
5. [Update the Function Code](#5-update-the-function-code)
6. [Rotate the KMS Master Key Manually](#6-rotate-the-kms-master-key-manually)
7. [Full Destroy](#7-full-destroy)

---

## 1. Trigger Secret Rotation Manually

This section covers secret credential rotation. To rotate the KMS master key, see [§6 — Rotate the KMS Master Key Manually](#6-rotate-the-kms-master-key-manually).

Trigger rotation via OCI Vault and monitor until complete:

```bash
WORK_REQUEST_ID=$(oci vault secret rotate \
  --secret-id "$SECRET_ID" \
  --query '"opc-work-request-id"' \
  --raw-output)

watch -n 10 "oci work-requests work-request get \
  --work-request-id \"$WORK_REQUEST_ID\" \
  --query 'data.{\"status\":\"status\",\"percent-complete\":\"percent-complete\"}'"
```

This triggers OCI's native four-step rotation protocol — `VERIFY_CONNECTION` → `CREATE_PENDING_VERSION` → `UPDATE_TARGET_SYSTEM` → `PROMOTE_PENDING_VERSION` — invoking the Function once per step in sequence. It exercises the same Vault Secret resource principal and `fn-invocation` IAM path that the scheduled rotation uses, making it the correct manual trigger for both routine rotation and IAM path validation.

`status: SUCCEEDED` and `percent-complete: 100.0` confirm all four steps completed (Ctrl-C to exit `watch`). `status: FAILED` means at least one step failed — check OCI Logging (see [§2 — Investigate a Failure](#2-investigate-a-failure)). The full rotation typically takes 30–60 seconds on a warm Function container; allow up to 2 minutes on a cold start.

Once the work request shows `SUCCEEDED`, use the verification commands below to confirm the rotation result.

**Verify — new secret version in Vault:**

```bash
oci vault secret-version list --secret-id $SECRET_ID
```

Look for the highest version number with stage `CURRENT`. The previous version should show `PREVIOUS`.

**Verify — Vault and Object Storage are consistent:**

Read the `CURRENT` credential from Vault and the credential from Object Storage, then compare:

```bash
VAULT_CRED=$(oci secrets secret-bundle get \
  --secret-id $SECRET_ID \
  --stage CURRENT \
  --query 'data."secret-bundle-content".content' \
  --raw-output | base64 -d)

OS_CRED=$(oci os object get \
  --namespace $NAMESPACE \
  --bucket-name $BUCKET_NAME \
  --name $OBJECT_NAME \
  --file - 2>/dev/null)

[ "$VAULT_CRED" = "$OS_CRED" ] && echo "CONSISTENT" || echo "MISMATCH"
```

Both values should be a 64-character hex string and must match. A mismatch indicates the rotation completed partially — see [§2 — Investigate a Failure](#2-investigate-a-failure).

**Verify — structured log entry in OCI Logging:**

```bash
oci logging-search search-logs \
  --search-query "search \"$COMPARTMENT_ID/$LOG_GROUP_ID\" | top 20 by datetime | sort by datetime desc" \
  --time-start "$(date -u -d '10 minutes ago' +%Y-%m-%dT%H:%M:%S.000Z)" \
  --time-end "$(date -u +%Y-%m-%dT%H:%M:%S.000Z)"
```

A complete successful rotation produces one successful step log for each of the four steps. Look for these messages in order:

1. `"VERIFY_CONNECTION succeeded"`
2. `"CREATE_PENDING_VERSION succeeded"` (or `"reusing existing PENDING version"` on retry)
3. `"UPDATE_TARGET_SYSTEM succeeded"`
4. `"PROMOTE_PENDING_VERSION succeeded"` and `"ONS notification sent"`

---

## 2. Investigate a Failure

### Find the error in OCI Logging

```bash
oci logging-search search-logs \
  --search-query "search \"$COMPARTMENT_ID/$LOG_GROUP_ID\" | where data.message = '*failed*' | top 10 by datetime | sort by datetime desc" \
  --time-start "$(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S.000Z)" \
  --time-end "$(date -u +%Y-%m-%dT%H:%M:%S.000Z)"
```

### Invoke VERIFY_CONNECTION directly to test connectivity

`VERIFY_CONNECTION` is read-only and makes no state changes — safe to call at any time:

```bash
oci fn function invoke \
  --function-id $FUNCTION_ID \
  --body "{\"secretId\":\"$SECRET_ID\",\"step\":\"VERIFY_CONNECTION\"}" \
  --file "-"
```

A successful response confirms the Function can authenticate to Vault and returns the current version number (e.g. `3` — the actual number will vary):

```json
{"responseCode": 200, "versionNo": 3, "returnMessage": "VERIFY_CONNECTION succeeded"}
```

A failure indicates Vault access could not be verified — for example, the Function lacks permission to read the secret, or the supplied secret OCID does not identify an accessible secret:

```json
{"responseCode": 400, "versionNo": null, "returnMessage": "VERIFY_CONNECTION failed: <error>"}
```

A common OCI error here is `NotAuthorizedOrNotFound`, which can mean either insufficient permission or that the referenced secret was not found or is not accessible.

All four rotation steps accept the same basic invocation format, but only `VERIFY_CONNECTION` is read-only. Directly invoking the other steps mutates rotation state and should be reserved for targeted troubleshooting. `PROMOTE_PENDING_VERSION` additionally requires a numeric `versionNo` field in the payload.

### Common failure states

| Error | Cause | State | Recovery |
|---|---|---|---|
| `missing request body` | Invocation sent with empty body | Nothing changed | Add request body with `secretId` and `step` fields |
| `missing secretId in request body` | Body is valid JSON but `secretId` key absent or blank | Nothing changed | Check the invocation payload |
| `invalid request body` | Body is not valid JSON or not valid UTF-8 | Nothing changed | Fix the invocation payload |
| `step field required` | `step` key absent or blank — bare `{"secretId":"..."}` payload used instead of full `SecretRotationInput` | Nothing changed | Use `oci vault secret rotate` for normal rotation; add `"step"` field for direct invocation |
| `VERIFY_CONNECTION failed: ...` | Function cannot read the secret — IAM policy missing or propagating, or the secret OCID is not found or not accessible | Nothing changed | Check the secret OCID and IAM policy; if IAM was just changed, wait 60s and retry |
| `CREATE_PENDING_VERSION failed: ...` | Vault API error creating or reading `PENDING` version | `PENDING` version may or may not exist | Retry — idempotent if `PENDING` was already created |
| `UPDATE_TARGET_SYSTEM failed: ...` | IAM policy missing for bucket write, bucket deleted, or network issue | `PENDING` version exists in Vault; target NOT updated | Restore IAM policy or bucket, retry |
| `PROMOTE_PENDING_VERSION failed: ...` | Vault promote API error or version in unexpected stage | `PENDING` exists in Vault; target IS updated | Inspect version stages, retry |
| `ONS notification failed` (WARNING in logs, rotation still succeeds) | IAM policy for ONS missing or propagating | Rotation complete, email not sent | Wait 60s, check IAM policy |
| Function returns `HTTP 502` / `FunctionInvokeExecutionFailed` | Unhandled exception in function code | Unknown | Check OCI Logging for stack trace |
| Function times out (120s) | Target system unreachable or very slow | Unknown — partial state possible | Check VCN/service gateway, check target |

### List all secret versions and their stages

```bash
oci vault secret-version list \
  --secret-id $SECRET_ID \
  --query 'data[*].{"version":"version-number","stages":"stages","created":"time-of-creation"}'
```

### Read the content of a specific secret version

```bash
# Replace <N> with the version number
oci secrets secret-bundle get \
  --secret-id $SECRET_ID \
  --version-number <N> \
  --query 'data."secret-bundle-content".content' \
  --raw-output | base64 -d
```

### Alerting on rotation failures

The rotation Function publishes an ONS notification only after a successful
rotation. Failed rotations surface in OCI Logging as ERROR-level entries.

For proactive failure alerting, create an OCI Connector Hub connector with:

- Source: Logging
- Source log group: the rotation Function log group
- Filter: ERROR-level rotation Function entries
- Target: Notifications
- Topic: the same ONS topic used for success notifications

If metric-based alerting is preferred, route the filtered logs from Connector Hub
to OCI Monitoring instead, then create a Monitoring alarm that fires when the
generated error-count metric is greater than zero.

---

## 3. Rollback to Previous Version

Use this when the current credential is broken and you need to restore the previous working one.

**Step 1 — Find the version to roll back to:**

```bash
oci vault secret-version list \
  --secret-id $SECRET_ID \
  --query 'data[*].{"version":"version-number","stages":"stages"}'
```

Note the version number with stage `PREVIOUS` (or whichever version you want to restore).

**Step 2 — Promote the previous version back to `CURRENT` in Vault:**

```bash
oci vault secret update \
  --secret-id $SECRET_ID \
  --current-version-number <N>
```

**Step 3 — Read the rolled-back credential value:**

```bash
ROLLED_BACK_CRED=$(oci secrets secret-bundle get \
  --secret-id $SECRET_ID \
  --query 'data."secret-bundle-content".content' \
  --raw-output | base64 -d)
```

**Step 4 — Restore the Object Storage target to match:**

```bash
printf '%s' "$ROLLED_BACK_CRED" | oci os object put \
  --namespace $NAMESPACE \
  --bucket-name $BUCKET_NAME \
  --name $OBJECT_NAME \
  --file - \
  --force
```

Vault and the target are now consistent. Verify that the credential value read from Vault in Step 3 matches the value in the Object Storage target before proceeding. Let the next scheduled rotation run rather than immediately triggering another rotation — re-triggering right after a manual rollback risks entering another inconsistent state if the target requires the current credential to authenticate the update.

---

## 4. Secret Version Pruning

OCI Vault retains all secret versions until explicitly pruned, up to a maximum of 30 active versions. Versions in `DEPRECATED` stage can be scheduled for deletion.

**List all versions with their stages:**

```bash
oci vault secret-version list \
  --secret-id $SECRET_ID \
  --query 'data[*].{"version":"version-number","stages":"stages","expires":"time-of-deletion"}'
```

**Schedule a specific version for deletion:**

```bash
# Minimum deletion window is 1 day, but use +2 days to stay clear of OCI's boundary check.
# Replace <N> with the version number to delete.
oci vault secret-version schedule-deletion \
  --secret-id $SECRET_ID \
  --secret-version-number <N> \
  --time-of-deletion "$(date -u -d '+2 days' +%Y-%m-%dT%H:%M:%S.000Z)"
```

**Cancel a scheduled deletion:**

```bash
oci vault secret-version cancel-deletion \
  --secret-id $SECRET_ID \
  --secret-version-number <N>
```

Do not delete `CURRENT`, `PENDING`, or `PREVIOUS` versions. Only `DEPRECATED` versions should be pruned.

---

## 5. Update the Function Code

Use this when the rotation Function image needs to be rebuilt and redeployed — for example, after a bug fix or dependency update.

**Step 1 — Build and push the new image:**

```bash
bash scripts/push-image.sh
```

**Step 2 — Force OCI Functions to pull the new image:**

OCI Functions caches the image on the first cold start. Pushing a new image to the same tag does not automatically cause the running function to use it. Force a fresh pull with:

```bash
oci fn function update \
  --function-id $FUNCTION_ID \
  --image "$IMAGE_URL"
```

This touches the function resource and causes OCI to pull the image on the next invocation.

**Step 3 — Verify the update:**

Invoke `VERIFY_CONNECTION` to confirm the new image can authenticate to Vault (read-only, no state changes):

```bash
oci fn function invoke \
  --function-id $FUNCTION_ID \
  --body "{\"secretId\":\"$SECRET_ID\",\"step\":\"VERIFY_CONNECTION\"}" \
  --file "-"
```

A successful response returns `{"responseCode": 200, "versionNo": N, "returnMessage": "VERIFY_CONNECTION succeeded"}`. If the response is an error, check OCI Logging for the stack trace (see [§2 — Investigate a Failure](#2-investigate-a-failure)).

---

## 6. Rotate the KMS Master Key Manually

This procedure rotates the customer-managed KMS master key (CMK) used to encrypt Vault secret material at rest. It does not rotate the secret credential value; use [§1 — Trigger Secret Rotation Manually](#1-trigger-secret-rotation-manually) for that.

OCI supports automatic KMS key rotation only for keys in `VIRTUAL_PRIVATE` vaults. For this `DEFAULT` vault, create a new key version manually when required.

Creating a new key version does not immediately re-encrypt existing secret versions. Future encryption operations use the new key version, while older key versions remain available to decrypt data encrypted before rotation.

**Step 1 — Create a new key version:**

```bash
NEW_KEY_VERSION_ID=$(oci kms management key-version create \
  --key-id "$MASTER_KEY_ID" \
  --endpoint "$VAULT_MANAGEMENT_ENDPOINT" \
  --query 'data.id' \
  --raw-output)

echo "$NEW_KEY_VERSION_ID"
```

**Step 2 — Verify the new key version exists:**

```bash
oci kms management key-version get \
  --key-id "$MASTER_KEY_ID" \
  --key-version-id "$NEW_KEY_VERSION_ID" \
  --endpoint "$VAULT_MANAGEMENT_ENDPOINT" \
  --query 'data.{"version-id":"id","lifecycle-state":"lifecycle-state","time-created":"time-created"}'
```

The `version-id` field should match `$NEW_KEY_VERSION_ID`. `lifecycle-state` should be `ENABLED`.

**Step 3 — List all key versions (optional):**

```bash
oci kms management key-version list \
  --key-id "$MASTER_KEY_ID" \
  --endpoint "$VAULT_MANAGEMENT_ENDPOINT" \
  --all \
  --query 'data[*].{"version-id":"id","time-created":"time-created","time-of-deletion":"time-of-deletion"}'
```

Old key versions remain available to decrypt data they previously encrypted. Schedule old key versions for deletion only after confirming no remaining ciphertext depends on them.

---

## 7. Full Destroy

Tears down all resources created by Terraform. The teardown script handles the required pre-destroy steps automatically:

```bash
bash scripts/destroy.sh
```

The script performs four pre-destroy cleanup steps, then runs `terraform destroy`:

1. Prepares and schedules secret deletion — disables auto-rotation (OCI blocks deletion while rotation is enabled), schedules the secret for deletion with a 2-day window, and removes it from Terraform state. The OCI provider would otherwise hang waiting for `DELETED` state or error with a `409-IncorrectState` conflict. The secret is permanently removed ~48 hours later.
2. Schedules vault deletion — schedules the vault for deletion with an 8-day window (one day above OCI's 7-day minimum to avoid boundary errors). Vault deletion cascades to all keys within it. Removes the vault and Terraform-managed key from Terraform state to prevent conflict with `PENDING_DELETION` state during `terraform destroy`.
3. Deletes the OCIR container repository (not managed by Terraform, so it must be cleaned up explicitly)
4. Empties the target Object Storage bucket (Terraform cannot delete a non-empty bucket)

The `terraform destroy` step typically takes 5–10 minutes end to end. Two resources are slow by design:

- **Functions application** — OCI deprovisions the underlying compute infrastructure, not just a metadata record. Expect 2–5 minutes.
- **ONS notification topic** — OCI cleans up all subscriptions (including pending email confirmations) before deleting the topic. Expect 2–5 minutes.

"Still destroying..." messages from Terraform for these resources are normal; let it run.

**After destroy — note:**

- The KMS Vault and its keys are placed in `PENDING_DELETION` by the destroy script with an 8-day window. They are permanently removed ~8 days after `destroy.sh` runs.

**Future work:**

- Make `destroy.sh` safely resumable after partial failure by checking OCI lifecycle state and Terraform state membership before each cleanup action. Reruns should skip work already completed instead of extending deletion windows or failing on already-removed resources.
