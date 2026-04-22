# OCI Secret Lifecycle Service — Design Document

**Status:** Draft (M0)
**Last updated:** 2026-04-21

---

## 1. Problem Statement

Secrets — database passwords, API keys, signing tokens — have a half-life. The longer a credential lives unchanged, the larger the blast radius if it is compromised: an attacker who exfiltrates a five-year-old password has five years' worth of access to revoke and investigate. Regular rotation shrinks that window.

Rotation is operationally hard to do well. Done manually it is error-prone and skipped under pressure. Done with a custom scheduler it becomes infrastructure that must itself be secured, monitored, and maintained. The right answer is to push rotation into the platform — to use a managed service that tracks state, handles versioning, and provides an audit trail by default.

This system demonstrates the canonical OCI pattern for doing exactly that: OCI Vault's native rotation scheduling triggers a customer-owned Function that performs the actual credential change. The Function is authenticated via Resource Principal — it carries no API keys, no passwords, no credentials of its own. IAM policy grants it exactly the permissions it needs and nothing more.

The result is a rotation system that is auditable (every rotation event is captured in OCI Logging), recoverable (Vault retains previous secret versions for rollback), and operationally simple (rotation runs on a schedule without human intervention).

---

## 2. Goals and Non-Goals

### Goals

- Demonstrate the native Vault rotation scheduling + custom Function pattern end-to-end
- Authenticate the Function via Resource Principal (no long-lived credentials on any resource)
- Produce an audit trail that lets an operator reconstruct exactly what happened during any rotation
- Show least-privilege IAM scoping: compartment-scoped policies, narrow dynamic group matching
- Provide written artifacts (design doc, ADRs, threat model, runbook) that explain the *why* at each decision point

### Non-Goals

- Multi-region replication (discussed in §10; not implemented)
- Admin UI or web endpoint
- Multi-tenant isolation (single compartment is sufficient for a reference implementation)
- Exhaustive test coverage (smoke tests and key unit tests only)
- Real production target system (mock target is sufficient to demonstrate the pattern)

---

## 3. Architecture

```mermaid
graph TD
    subgraph compartment["Compartment: secret-rotation-demo"]
        subgraph iam["IAM"]
            DG["Dynamic Group<br/>(matches Function OCID)"]
            POL["Policies<br/>• DG can use secret-family<br/>• vaultsecret can invoke Function"]
        end

        subgraph vault_group["OCI Vault"]
            KMS["KMS Master Key"]
            SEC["Secret<br/>(rotation schedule attached)"]
            KMS -- "encrypts" --> SEC
        end

        subgraph fn_group["OCI Functions"]
            FNA["Function App"]
            FN["rotation-handler<br/>(Python 3.12)"]
            FNA --> FN
        end

        MT["Mock Target<br/>(in-memory / Object Storage stub)"]

        subgraph obs["Observability"]
            LG["Log Group<br/>+ Function logs"]
            EV["Events Rule<br/>(secret version created)"]
            NT["Notifications Topic"]
        end

        SEC -- "invokes on schedule" --> FN
        FN -- "rotates credential on" --> MT
        FN -- "writes new version to" --> SEC
        SEC -- "emits event" --> EV
        EV --> NT
        FN -- "structured logs" --> LG
        DG -. "Resource Principal auth" .-> FN
        POL -. "governs" .-> DG
    end
```

### Component walkthrough

**OCI Vault + KMS key.** The Vault holds the secret and its version history. A customer-managed KMS master key encrypts secret material at rest. The secret resource carries a `rotation_config` that specifies the rotation interval and the target Function OCID — this is what drives the schedule without any custom cron infrastructure.

**OCI Function (rotation handler).** A Python 3.12 function invoked by the Vault rotation scheduler. It reads the current secret, generates a new credential, updates the mock target, then writes a new pending version to Vault and promotes it to current. It authenticates to OCI APIs using Resource Principal — the Function's OCID is the credential.

**Mock target.** A stub that simulates a downstream service accepting a credential update. In a real deployment this would be replaced by a database password change, an API key rotation call, or a similar operation. The pattern is identical regardless of target.

**IAM dynamic group + policies.** The Function's OCID is matched by a dynamic group rule. Two policy statements grant: (1) the dynamic group permission to read and write secrets in the compartment, and (2) the `vaultsecret` service principal permission to invoke the Function. Both policies are compartment-scoped.

**OCI Logging + Events.** The Function emits structured JSON logs to OCI Logging. An Events rule subscribes to `com.oraclecloud.vaultsecret.createsecretversion` and forwards to a Notifications topic. This gives both real-time alerting and a queryable audit trail.

---

## 4. Rotation Flow

```mermaid
sequenceDiagram
    participant VS as OCI Vault Scheduler
    participant FN as Rotation Function
    participant MT as Mock Target
    participant VW as Vault (write)
    participant LG as OCI Logging

    VS->>FN: invoke (rotation trigger)
    FN->>VW: GetSecretBundle (read current version)
    VW-->>FN: current credential value
    FN->>FN: generate new credential
    FN->>VW: CreateSecretVersion(new value, stage=PENDING)
    VW-->>FN: pending version number
    FN->>MT: UpdateCredential(new value)
    MT-->>FN: success
    FN->>VW: UpdateSecretVersionStage(PENDING → CURRENT)
    VW-->>FN: success
    VW--)LG: secret-version-created event
    FN--)LG: structured rotation log entry
    Note over VW: Previous CURRENT version<br/>moves to PREVIOUS (retained for rollback)
```

**Failure handling** is covered in detail in [ADR 0003](adr/0003-rotation-state-machine.md). Three partial-failure cases exist: (1) CreateSecretVersion fails — target untouched, state consistent, safe to retry; (2) UpdateCredential fails after PENDING created — CURRENT unchanged, target consistent with CURRENT, re-trigger creates a fresh PENDING; (3) UpdateSecretVersionStage fails after target update — target holds new credential but CURRENT still reflects old, re-trigger recovers by overwriting both.

---

## 5. Design Decisions

### Native Vault rotation scheduling over custom cron

OCI Vault's `rotation_config` on a secret resource manages the schedule, invocation, and retry. Building a custom scheduler would require additional infrastructure (a cron job, a VM or serverless trigger, state tracking) that must itself be secured and maintained. The native scheduler is managed, audited, and zero-maintenance. See [ADR 0001](adr/0001-native-rotation-scheduler.md).

### Resource Principal for Function authentication

The Function authenticates to OCI APIs using its own OCID as the credential — no API keys, no config files, no secrets stored on the Function. The IAM dynamic group rule matches the specific Function OCID, and policies grant only the permissions needed for rotation. If the Function image is compromised, the blast radius is bounded by the policy scope. See [ADR 0002](adr/0002-resource-principal-auth.md).

### Vault `DEFAULT` protection mode (software keys)

Software-protected keys are used for this reference implementation. HSM-backed (`VIRTUAL_PRIVATE`) keys provide stronger non-exportability guarantees but cost significantly more and require a dedicated HSM partition. The upgrade path is documented in §10. The rotation *pattern* is identical regardless of key protection mode.

### Single compartment

Multi-compartment separation (e.g., separating the Vault from the Function) adds policy complexity without demonstrating additional patterns. A single compartment is sufficient for a reference implementation. Cross-compartment patterns are documented as future work in §10.

### Mock target

Rotating against a real database or third-party API introduces external dependencies, costs, and setup complexity that distract from the pattern being demonstrated. A mock target that accepts a credential update call demonstrates the integration point without the noise.

---

## 6. Rotation State Machine

Secret versions move through the following states: `PENDING` → `CURRENT` → `PREVIOUS` → `DEPRECATED`. The Function drives the `PENDING → CURRENT` transition. The Vault automatically moves the former `CURRENT` to `PREVIOUS` when a new version is promoted.

The full state diagram — including the rollback path when target update fails after a pending version has been written — is in [ADR 0003](adr/0003-rotation-state-machine.md).

---

## 7. Security Model

**Trust boundaries.** The rotation Function is the only principal that crosses the boundary between the Vault (where the secret lives) and the target (where the credential is applied). This boundary crossing is governed by IAM policy on both sides.

**Authentication model.** No component holds a long-lived credential. The Function authenticates via Resource Principal. Vault's scheduler invokes the Function using the `vaultsecret` service principal, which IAM policy authorizes to call `functions:invokeFunction`.

**Least-privilege scoping.** All policies are compartment-scoped, not tenancy-scoped. The dynamic group matches the specific Function OCID, not a broad rule like "all functions in the tenancy." If the compartment is deleted or the Function is redeployed to a new OCID, the policy stops matching — the narrowing is intentional.

**Secret version retention.** Vault retains previous versions (configurable, default two versions). This protects against accidental deletion and provides a rollback path. Soft-delete on the secret itself adds a further recovery window before permanent deletion.

See [docs/threat-model.md](threat-model.md) for the full STRIDE analysis.

<To be filled in at M7. Must cover: partial backend configuration pattern (backend.hcl kept out of version control) and why the OCI native backend requires no separately-managed credentials (auth flows through ~/.oci/config, same as the OCI provider).>

---

## 8. Observability Model

**What is logged:**
- Every Function invocation (start, success, failure) via structured JSON to OCI Logging
- Every Vault API call is captured in OCI Audit automatically (cannot be disabled)
- Secret version creation events via OCI Events → Notifications

**What is alerted:**
- Secret version creation events trigger a Notifications topic (email or HTTPS endpoint)
- Function invocation failures surface in OCI Logging and can be queried or alerted on

**How to investigate:** See [docs/runbook.md](runbook.md) for exact CLI commands to query logs, list secret versions, and reconstruct the sequence of events after a rotation.

---

## 9. Operational Considerations

**Rotation cadence tradeoffs.** More frequent rotation reduces the window of exposure for a compromised credential but increases the operational load on the target system and the risk of a partial-rotation window (the period between the target being updated and Vault confirming the new version). For most use cases, 30–90 day intervals balance risk reduction against operational noise.

**Blast radius of failure.** If the Function fails after updating the target but before writing to Vault, the target holds a new credential that Vault does not know about. The recovery path — re-trigger rotation — is documented in the runbook. The state machine is designed to detect and recover from this case.

**Rollback path.** Previous secret versions are retained in Vault. Rolling back means promoting the previous version to `CURRENT` and re-applying the old credential to the target. The runbook documents the exact steps.

---

## 10. Future Work

- **Multi-region replication.** Vault secrets can be replicated to a secondary region using OCI Vault cross-region replication. The rotation Function would need to be deployed in both regions, or a single-region Function would need to update both Vault instances. Not implemented here.
- **Cross-tenancy access.** Secrets shared across tenancies require cross-tenancy IAM policies. The pattern is documented in the OCI IAM docs but is out of scope for this reference.
- **HSM-backed keys.** Upgrading from `DEFAULT` to `VIRTUAL_PRIVATE` protection mode requires destroying and recreating the KMS key (and therefore the secret). Plan for this before using this pattern with highly sensitive material.
- **Real target integrations.** Replacing the mock target with a real database (e.g., using OCI Database's password rotation API) or a third-party secret (e.g., a GitHub PAT) follows the same pattern — only `target_client.py` changes.
- **CI/CD for Function updates.** A GitHub Actions workflow that builds, pushes, and redeploys the Function on merge to `main` is a natural extension. The workflow file is included in the repo as a pattern reference.
