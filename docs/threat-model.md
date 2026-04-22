# OCI Secret Lifecycle Service — Threat Model

**Status:** Accepted
**Last updated:** 2026-04-22

---

## Overview

This document applies STRIDE threat analysis to the OCI secret rotation system. The system has two trust boundaries: between the Vault (where the secret lives) and the rotation Function (which reads and writes it), and between the Function and the rotation target (the Object Storage bucket that holds the current credential value).

Each identified threat is accompanied by the specific OCI primitive that mitigates it. A generic mitigation ("use strong authentication") is not sufficient — every mitigation names the service feature or configuration that enforces it.

---

## STRIDE Analysis

### Spoofing — Unauthorized Rotation Trigger

**Threat:** An unauthorized principal invokes the rotation Function to trigger an unsolicited rotation, cause unnecessary credential churn, or attempt to observe the new credential by controlling the target.

**Mitigation:**
- IAM policy `Allow service vaultsecret to use fn-invocation in compartment id ...` restricts Function invocation from the scheduled path to the `vaultsecret` managed service principal only. No other principal — including the operator who provisioned the infrastructure — holds `fn-invocation` on the Function unless explicitly granted separately.
- Direct invocation via `oci fn function invoke` requires IAM `functions:invokeFunction` scoped to the Function OCID. Only principals explicitly granted this permission in IAM can invoke the Function directly.
- OCI Functions does not expose an unauthenticated HTTP endpoint. Every invocation path requires a signed OCI API request; unsigned requests are rejected at the API gateway layer.

---

### Tampering — Secret Material Modification

**Threat:** Secret material is modified in transit between Vault and the Function, or altered at rest in Vault or Object Storage without authorization.

**Mitigation:**
- **In transit:** All OCI SDK calls use TLS 1.2+ to HTTPS endpoints. The OCI SDK enforces certificate verification; there is no plaintext path.
- **At rest in Vault:** Secret material is encrypted with an AES-256 customer-managed KMS key (`protection_mode = "SOFTWARE"`). Disabling or deleting the KMS key revokes access to all secrets it protects — this is the break-glass mechanism for emergency revocation.
- **At rest in Object Storage:** The target bucket is `access_type = "NoPublicAccess"`. IAM policy restricts write access to the rotation Function's dynamic group, scoped to the specific bucket name (`where target.bucket.name = '...'`). No public URL exists for the credential object.
- OCI Vault enforces soft-delete: a secret cannot be silently destroyed. It enters `PENDING_DELETION` state with a configurable retention window (1–30 days) before permanent deletion, providing a recovery path against accidental or malicious deletion.

---

### Repudiation — Disputing That Rotation Occurred

**Threat:** An operator or auditor disputes whether a specific rotation occurred, what credential was written, or which principal triggered the rotation.

**Mitigation:**
- **OCI Audit** captures every API call — Vault reads, Vault writes, Object Storage puts, Function invocations, and ONS publishes — with caller identity (including the Function OCID for Resource Principal calls), timestamp, request ID, and source IP. OCI Audit cannot be disabled at the tenancy level; it is managed by OCI and is available for forensic reconstruction.
- The rotation Function emits structured JSON log entries to OCI Logging at each phase (`start`, `read`, `vault_pending`, `target_update`, `vault_promote`, `complete`). Each entry includes the secret OCID, phase name, and version number where relevant.
- After each successful rotation the Function publishes a message to the ONS topic. The message includes the secret OCID, status, and is delivered to subscribed endpoints (email, HTTPS webhook). This provides an out-of-band confirmation trail independent of OCI Logging.
- Vault retains all secret versions indefinitely unless explicitly pruned. Any previous version can be retrieved by version number (`oci secrets secret-bundle get --version-number <N>`), enabling forensic reconstruction of the credential sequence.

---

### Information Disclosure — Credential Leakage

**Threat:** The current credential value is exposed via log output, error messages, API responses, or misconfigured access controls on the target bucket.

**Mitigation:**
- The rotation Function **does not log the credential value at any phase**. `rotation.py` logs phase names, secret OCIDs, and version numbers — never the plaintext credential. The new credential is generated in memory, passed directly to `target_client.update_credential()`, and never written to any logging context.
- OCI Vault returns secret content as a base64-encoded payload. The Function decodes it in memory; the decoded string is used directly in the credential update call and not assigned to any variable that logging infrastructure might capture.
- The Object Storage bucket is `NoPublicAccess`. Access requires a signed OCI API request from a principal with IAM permission. No pre-authenticated request URLs are created.
- `terraform.tfvars` (which contains tenancy OCIDs) is `.gitignore`d and is never committed. Secret content is never written to any file tracked by the repository.
- Function application config contains the target bucket name, namespace, and secret OCID — resource identifiers, not credential material. Even if this config were read by an unauthorized principal, no credential value is exposed.

---

### Denial of Service — Rotation Prevented or Disrupted

**Threat:** The rotation Function is unavailable, rate-limited, or its invocation is blocked, preventing scheduled rotation from completing.

**Mitigation:**
- OCI Functions and OCI Vault are managed services with OCI SLAs. Transient unavailability is handled by the Vault scheduler's built-in retry behavior.
- A failed rotation does **not** invalidate the current credential. The CURRENT version in Vault remains valid and usable until a successful rotation completes. The system degrades gracefully — credentials continue to work, just without renewal.
- The 30-day default rotation interval provides a large window before a missed rotation becomes operationally significant. Manual rotation (`oci vault secret rotate`) is always available as an out-of-band fallback.
- The Function has a 120-second timeout (`timeout_in_seconds = 120`). An unreachable or unresponsive target causes a clean timeout and a logged failure rather than a hung invocation.
- OCI Logging captures structured log entries for every failed rotation phase. The runbook provides exact CLI queries to investigate missed rotations.

---

### Elevation of Privilege — Function Accesses Out-of-Scope Resources

**Threat:** The rotation Function reads or modifies secrets, buckets, or other OCI resources beyond its explicitly authorized scope.

**Mitigation:**
- **Secret scope:** IAM policy restricts secret-family access with `where target.secret.name = '<name>'`. Even if the dynamic group matching rule were broadened, the policy condition limits the effective secret scope to the single named secret.
- **Bucket scope:** IAM policy restricts Object Storage access with `where target.bucket.name = '<name>'`. The Function cannot read or write any other bucket in the compartment.
- **Dynamic group scope:** The matching rule uses `ALL {resource.type = 'fnfunc', resource.id = '<ocid>'}`. Both conditions must match: the resource must be a Function and must have the specific OCID. Any other Function deployed in the same compartment does not match.
- **Compartment scope:** All policies are `in compartment id <ocid>` — not `in tenancy`. A misconfigured policy cannot grant access outside the specific compartment.

---

## Rotation-Specific Failure Modes

### Target updated, Vault write fails

**Scenario:** `update_credential()` (Phase 4) succeeds — Object Storage holds the new credential — but `create_pending_version()` (Phase 3) was already called and the `promote_to_current()` call (Phase 5) fails.

*Note:* In the implemented code, Phase 3 (Vault write) executes before Phase 4 (target update). If Phase 3 fails, neither side is changed. If Phase 5 fails after Phase 4 succeeds, the target holds the new credential but Vault CURRENT holds the old one.

**State:** Object Storage and Vault CURRENT are inconsistent. See [ADR 0003](adr/0003-rotation-state-machine.md) for the full ordering rationale.

**Recovery:** Re-triggering rotation generates a fresh credential, overwrites the target (last-write-wins), writes a new PENDING version to Vault, and promotes it. Both sides converge on the new credential.

---

### Vault PENDING written, target update fails

**Scenario:** `create_pending_version()` (Phase 3) succeeds — a PENDING version exists in Vault — but `update_credential()` (Phase 4) raises `TargetUpdateError`.

**State:** Vault has an orphaned PENDING version. CURRENT still holds the old credential. Target is consistent with CURRENT.

**Recovery:** Re-triggering rotation calls `update_secret()` again; OCI automatically demotes the orphaned PENDING to DEPRECATED when the new PENDING is created. Rotation proceeds from a consistent state. See [ADR 0003](adr/0003-rotation-state-machine.md).

---

### Duplicate concurrent rotation invocations

**Scenario:** A manual rotation trigger is sent while a scheduled rotation is already in flight, or two manual triggers are sent close together.

**State:** Two Function invocations execute concurrently, each generating a different credential and racing to write to Vault and Object Storage.

**Mitigation:** Both Vault's `update_secret()` and Object Storage's `put_object()` are last-write-wins. One invocation wins the race; the other produces an orphaned PENDING version that is automatically demoted to DEPRECATED on the winner's `update_secret()` call. The resulting credential set is self-consistent — one rotation wins, the other is effectively a no-op. OCI Audit captures both invocations and their caller identities for forensic reconstruction.

---

### Replay of old rotation triggers

**Scenario:** A captured or stale invocation request is replayed to cause an unsolicited rotation.

**Mitigation:** OCI Function invocations use OCI request signing (SigV4-equivalent). The signature includes a `Date` header that OCI validates server-side — requests older than 5 minutes are rejected. Replay beyond that window is not possible at the OCI API layer. Additionally, the IAM policy restricts `fn-invocation` to the `vaultsecret` managed service principal, making it structurally difficult for an external attacker to forge a valid invocation request.
