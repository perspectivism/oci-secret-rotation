# ADR 0001: Use Native OCI Vault Rotation Scheduling

**Status:** Accepted
**Date:** 2026-04-22

## Context

Secret rotation requires a scheduler to trigger the rotation Function on a regular cadence. The scheduler must fire reliably without human intervention, leave an auditable record of when rotation was triggered, and carry no new infrastructure cost or maintenance burden of its own.

Three approaches were evaluated:

- **OCI Vault native `rotation_config`** — the secret resource carries a `rotation_config` block specifying an ISO 8601 interval and the target Function OCID; OCI manages invocation
- **OCI Cloud Scheduler + Function trigger** — a separate Cloud Scheduler resource fires on a cron expression and invokes the Function
- **Self-hosted cron** — a compute resource (VM or Kubernetes CronJob) runs a scheduled script

## Decision

Use OCI Vault's native `rotation_config` on the secret resource:

```hcl
rotation_config {
  is_scheduled_rotation_enabled = true
  rotation_interval              = "P30D"
  target_system_details {
    target_system_type = "FUNCTION"
    function_id        = var.function_ocid
  }
}
```

## Consequences

**Easier:**
- No additional scheduling infrastructure to provision, secure, or maintain
- Rotation state (last triggered, next trigger, version history) is co-located with the secret in Vault — a single resource holds the complete rotation story
- Every scheduler-initiated invocation is captured in OCI Audit automatically under the `vaultsecret` service principal
- The `vaultsecret` service manages invocation using its own managed service principal; no separate IAM principal or API key is required for the scheduler

**Harder:**
- `rotation_config` requires the Function OCID at secret creation time, creating a circular Terraform dependency: the secret needs the Function OCID, and the Function app config needs the secret OCID. This is resolved by declaring `function_ocid` as a static input variable in `terraform.tfvars` rather than wiring it from the function module output. The OCID is stable after initial deployment and changes only if the Function resource is destroyed and recreated.
- Schedule granularity is calendar-based (ISO 8601 duration, minimum one day). Sub-daily rotation is not supported.
- Disabling auto-rotation is required before OCI will schedule a secret for deletion — a non-obvious operational step that must be performed before `terraform destroy` can remove a secret. Documented in the runbook.

## Alternatives Considered

**OCI Cloud Scheduler:** Requires provisioning and maintaining a separate resource with its own lifecycle. Does not carry native awareness of secret state — it fires an invocation but knows nothing about the current version or rotation history. Adds a second service to monitor and keep in sync with the secret's lifecycle.

**Self-hosted cron (VM or Kubernetes CronJob):** Requires a running compute resource, increasing cost and operational surface. The cron job itself must be secured, monitored, and updated. Any outage of the compute resource silently skips rotation without alerting.

**Event-driven rotation (rotate when the secret reaches a target age):** OCI Events Service does not expose secret access events or secret age events usable as rotation triggers. The only related events published by the vault service are Customer Secret Key operations, not Vault secret version operations. Confirmed empirically during M6 implementation — audit log inspection revealed only `Customer Secret Key - Create/Update/Delete` event types for this service.
