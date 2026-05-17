# OCI Secret Lifecycle Service — Threat Model

**Status:** Accepted
**Last updated:** 2026-05-16

---

## Contents

- [Overview](#overview)
- [STRIDE Analysis](#stride-analysis)
  - [Spoofing — Unauthorized Rotation Trigger](#spoofing--unauthorized-rotation-trigger)
  - [Tampering — Secret Material Modification](#tampering--secret-material-modification)
  - [Repudiation — Disputing That Rotation Occurred](#repudiation--disputing-that-rotation-occurred)
  - [Information Disclosure — Credential Leakage](#information-disclosure--credential-leakage)
  - [Denial of Service — Rotation Prevented or Disrupted](#denial-of-service--rotation-prevented-or-disrupted)
  - [Elevation of Privilege — Function Accesses Out-of-Scope Resources](#elevation-of-privilege--function-accesses-out-of-scope-resources)
- [Rotation-Specific Failure Modes](#rotation-specific-failure-modes)
  - [Target updated, Vault promote fails](#target-updated-vault-promote-fails)
  - [Vault `PENDING` written, target update fails](#vault-pending-written-target-update-fails)
  - [Duplicate concurrent rotation invocations](#duplicate-concurrent-rotation-invocations)
  - [Replay of old rotation triggers](#replay-of-old-rotation-triggers)
- [Operator Workstation Credentials](#operator-workstation-credentials)

---

## Overview

This document applies STRIDE threat analysis to the OCI secret rotation system. The system has two trust boundaries: between the Vault (where the secret lives) and the rotation Function (which reads and writes it), and between the Function and the rotation target (the Object Storage bucket that holds the current credential value).

Each identified threat is accompanied by the specific OCI primitive that mitigates it. A generic mitigation ("use strong authentication") is not sufficient — every mitigation names the service feature or configuration that enforces it.

---

## STRIDE Analysis

### Spoofing — Unauthorized Rotation Trigger

**Threat:** An unauthorized principal invokes the rotation Function to trigger an unsolicited rotation, cause unnecessary credential churn, or attempt to observe the new credential by controlling the target.

**Mitigation:**
- A dedicated IAM dynamic group matches the specific Vault Secret OCID (`resource.type = 'vaultsecret', resource.id = '<ocid>'`). Only that dynamic group is granted `use fn-invocation` scoped to the specific Function OCID (`where target.function.id = '...'`). Within the policies provisioned by this system, no other principal — including the operator who provisioned the infrastructure — holds `fn-invocation` on the Function.
- Direct invocation via `oci fn function invoke` requires IAM `functions:invokeFunction` scoped to the Function OCID. Only principals explicitly granted this permission in IAM can invoke the Function directly.
- OCI Functions does not expose an unauthenticated HTTP endpoint. Every invocation path requires a signed OCI API request; unsigned requests are rejected at the API gateway layer.

---

### Tampering — Secret Material Modification

**Threat:** Secret material is modified in transit between Vault and the Function, or altered at rest in Vault or Object Storage without authorization.

**Mitigation:**
- **In transit:** All OCI SDK calls use TLS 1.2+ to HTTPS endpoints. The OCI SDK enforces certificate verification; there is no plaintext path.
- **At rest in Vault:** Secret material is encrypted with an AES-256 customer-managed KMS key (`protection_mode = "SOFTWARE"`). Disabling the KMS key immediately blocks decryption of all secrets it protects; scheduling key deletion provides a permanent revocation path after OCI's retention window.
- **KMS key lifecycle:** Automatic KMS key rotation is available only for `VIRTUAL_PRIVATE` vault keys. This deployment uses a `DEFAULT` vault; the master key must be rotated manually when required (see [runbook §6](runbook.md#6-rotate-the-kms-master-key-manually)).
- **At rest in Object Storage:** The target bucket is `access_type = "NoPublicAccess"`. IAM policy restricts write access to the rotation Function's dynamic group, scoped to the specific bucket name (`where target.bucket.name = '...'`). No public URL exists for the credential object.
- OCI Vault enforces soft-delete: a secret cannot be silently destroyed. It enters `PENDING_DELETION` state with a configurable retention window (1–30 days) before permanent deletion, providing a recovery path against accidental or malicious deletion.

---

### Repudiation — Disputing That Rotation Occurred

**Threat:** An operator or auditor disputes whether a specific rotation occurred, what credential was written, or which principal triggered the rotation.

**Mitigation:**
- **OCI Audit** captures API calls such as Vault reads, Vault writes, Function invocations, and ONS publishes, including caller identity (such as the Function OCID for Resource Principal calls), timestamp, request ID, and source IP. OCI Audit cannot be disabled at the tenancy level; it is managed by OCI and is available for forensic reconstruction. Note: object-level `put_object` operations are not captured by OCI Audit; capture them with Object Storage service logs if needed. The rotation Function's structured log entry at the `UPDATE_TARGET_SYSTEM` step provides the application-level evidence of the write.
- The rotation Function emits a structured JSON log entry to OCI Logging for each rotation step. Because OCI invokes the Function once per step, each invocation's log entry records the outcome of that step independently. Each entry includes the secret OCID, step name, and version number where relevant.
- After each successful rotation the Function publishes a message to the ONS topic. The message includes the secret OCID and status, and is delivered to subscribed email endpoints. This provides an out-of-band confirmation trail independent of OCI Logging.
- Vault retains secret versions until explicitly pruned, subject to OCI Vault version limits. Any retained previous version can be retrieved by version number (`oci secrets secret-bundle get --version-number <N>`), enabling forensic reconstruction of the credential sequence.

---

### Information Disclosure — Credential Leakage

**Threat:** The current credential value is exposed via log output, error messages, API responses, or misconfigured access controls on the target bucket.

**Mitigation:**
- The rotation Function **does not log the credential value at any step**. `rotation.py` logs step names, secret OCIDs, and version numbers — never the plaintext credential. The new credential is generated in memory, passed directly to `target_client.update_credential()`, and never written to any logging context.
- OCI Vault returns secret content as a base64-encoded payload. The Function decodes it in memory and passes it directly to the credential update call; it is never included in log fields, error messages, or structured logging context.
- The Object Storage bucket is `NoPublicAccess`. Access requires a signed OCI API request from a principal with IAM permission. No pre-authenticated request URLs are created.
- `terraform.tfvars` (which contains tenancy OCIDs) is `.gitignore`d and is never committed. Secret content is never written to any file tracked by the repository.
- Function application config contains the target bucket name, namespace, target object name, and ONS topic OCID — resource identifiers, not credential material. Even if this config were read by an unauthorized principal, no credential value is exposed. The secret OCID arrives in the invocation payload at runtime and is not stored in Function config.

---

### Denial of Service — Rotation Prevented or Disrupted

**Threat:** The rotation Function is unavailable, rate-limited, or its invocation is blocked, preventing scheduled rotation from completing.

**Mitigation:**
- OCI Functions and OCI Vault are managed services with OCI SLAs. Transient failures should be investigated through logs; OCI retries individual failed steps independently — a step failure does not restart the full rotation cycle.
- A failed rotation does **not** invalidate the current credential. The `CURRENT` version in Vault remains valid and usable until a successful rotation completes. The system degrades gracefully — credentials continue to work, just without renewal.
- The 30-day default rotation interval provides a large window before a missed rotation becomes operationally significant. Manual rotation (`oci vault secret rotate`) can be used as an out-of-band fallback when IAM and rotation configuration are healthy.
- The Function has a 120-second timeout (`timeout_in_seconds = 120`). An unreachable or unresponsive target causes a clean timeout and a logged failure rather than a hung invocation.
- The Function emits structured log entries for failed rotation steps, which are captured in OCI Logging when function logging is enabled. The runbook provides exact CLI queries to investigate missed rotations.

---

### Elevation of Privilege — Function Accesses Out-of-Scope Resources

**Threat:** The rotation Function reads or modifies secrets, buckets, or other OCI resources beyond its explicitly authorized scope.

**Mitigation:**
- **Secret scope:** IAM policy restricts `secret-family` access with `where target.secret.id = '<ocid>'`. Even if the dynamic group matching rule were broadened, the policy condition limits the effective secret scope to the single secret OCID.
- **Bucket scope:** IAM policy restricts Object Storage access with `where target.bucket.name = '<name>'`. The Function cannot read or write any other bucket in the compartment.
- **Dynamic group scope:** The matching rule uses `ALL {resource.type = 'fnfunc', resource.id = '<ocid>'}`. Both conditions must match: the resource must be a Function and must have the specific OCID. Any other Function deployed in the same compartment does not match.
- **Compartment scope:** All policies are `in compartment id <ocid>` — not `in tenancy`. A misconfigured policy cannot grant access outside the specific compartment.
- **Network egress scope:** The Function application runs in a private subnet with no public IPs, no Internet Gateway, and no NAT Gateway. Its route table and security list allow outbound HTTPS only to the Oracle Services Network through a Service Gateway. This prevents the rotation code from reaching arbitrary public internet endpoints for data exfiltration; access to OCI services is still governed by IAM policy.

---

## Rotation-Specific Failure Modes

Step names below refer to the four-step rotation protocol defined in [ADR 0003](adr/0003-rotation-state-machine.md).

### Target updated, Vault promote fails

**Scenario:** The `CREATE_PENDING_VERSION` and `UPDATE_TARGET_SYSTEM` steps both succeed — a `PENDING` version exists in Vault and Object Storage holds the new credential — but the `PROMOTE_PENDING_VERSION` step fails.

**State:** Object Storage and Vault `CURRENT` are inconsistent. See [ADR 0003](adr/0003-rotation-state-machine.md) for the full ordering rationale.

**Recovery:** OCI retries the `PROMOTE_PENDING_VERSION` step. The three-way convergence check finds the version in `PENDING` stage and promotes it. No new credential is generated; both sides converge on the same credential.

---

### Vault `PENDING` written, target update fails

**Scenario:** The `CREATE_PENDING_VERSION` step succeeds — a `PENDING` version exists in Vault — but the `UPDATE_TARGET_SYSTEM` step fails.

**State:** Vault has a `PENDING` version. `CURRENT` still holds the old credential. Target is consistent with `CURRENT`.

**Recovery:** OCI retries the `UPDATE_TARGET_SYSTEM` step directly. The step reads the existing `PENDING` version from Vault and retries the target write with the same credential. No new `PENDING` version is created and no version is demoted. See [ADR 0003](adr/0003-rotation-state-machine.md).

---

### Duplicate concurrent rotation invocations

**Scenario:** A manual rotation trigger is sent while a scheduled rotation is already in flight, or two manual triggers are sent close together.

**State:** Two rotation cycles overlap. If their `CREATE_PENDING_VERSION` steps race, each may generate a different credential before either observes the other's `PENDING` version — resulting in two different credentials racing to write to Vault and Object Storage.

**Mitigation / residual risk:** The implementation has no lock or compare-and-swap around the target write and Vault promotion. Under concurrent invocations, the `PENDING` version created by one invocation may be demoted to `DEPRECATED` when another invocation creates its own `PENDING` version. There is no guarantee that the invocation that writes last to the target is the same invocation that promotes its Vault version to `CURRENT`. In an adverse interleaving, Vault `CURRENT` and the rotation target could hold different credentials.

The practical mitigation is operational: treat rotation for a given secret as single-flight. Avoid manual invocation while a scheduled or manual rotation is already in progress. OCI Audit and Function logs capture both invocations and their caller identities, which supports forensic reconstruction if overlap occurs.

For this Object Storage demonstration target, manually re-triggering rotation once no other rotation is in flight should restore consistency: a successful single invocation overwrites the target and promotes the same credential to Vault `CURRENT`. For real targets that require the current credential to authenticate a rotation, this inconsistency may require target-specific break-glass recovery, such as resetting the credential through an administrative channel, then restoring Vault and the target to the same known-good value.

---

### Replay of old rotation triggers

**Scenario:** A captured or stale invocation request is replayed to cause an unsolicited rotation.

**Mitigation:** OCI Function invocations use OCI request signing (SigV4-equivalent). The signature includes a signed `date`/`x-date` header used for replay protection; OCI rejects requests when clock skew exceeds five minutes. Replay beyond that window is not possible at the OCI API layer. Additionally, the IAM policy restricts `fn-invocation` to the specific Vault Secret dynamic group scoped to the rotation Function OCID, making it structurally difficult for an external attacker to forge a valid invocation request.

---

## Operator Workstation Credentials

**Out of scope for the runtime threat model, but noted for completeness.**

**Threat:** Operators interact with this system using the OCI CLI, which stores a long-lived API key in `~/.oci/`. If an operator workstation is compromised, an attacker could use that key to perform any OCI actions permitted by the IAM user, which may include invoking the Function, reading secret versions, or modifying IAM policy.

**Runtime boundary:** No long-lived credentials are stored on OCI runtime resources — the rotation Function and Vault Secret both authenticate via Resource Principal.

**Mitigations at the operator level:**
- Restrict OCI IAM user permissions to the minimum required for deployment and operations
- Use OCI CLI profiles tied to IAM users with MFA enabled, and require MFA for console access
- Rotate OCI API keys on a regular schedule and promptly revoke keys when team members leave the project
