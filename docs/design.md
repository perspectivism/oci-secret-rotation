# OCI Secret Lifecycle Service — Design Document

**Status:** Accepted
**Last updated:** 2026-05-04

---

## 1. Problem Statement

Secrets — database passwords, API keys, signing tokens — become riskier the longer they remain unchanged. Over time they may be copied into scripts, cached by clients, logged by mistake, shared during incidents, or retained in systems no one actively maintains. If one of those credentials is compromised, responders must treat its entire lifetime as the possible exposure window. Regular rotation limits that window and reduces the amount of history that must be investigated.

Rotation is operationally hard to do well. Done manually it is error-prone and skipped under pressure. Done with a custom scheduler it becomes infrastructure that must itself be secured, monitored, and maintained. The right answer is to push rotation into the platform — to use a managed service that tracks state, handles versioning, and provides an audit trail by default.

This system demonstrates the canonical OCI pattern for doing exactly that: OCI Vault's native rotation scheduling triggers a customer-owned Function that performs the actual credential change. The Function is authenticated via Resource Principal — it carries no API keys, no passwords, no credentials of its own. IAM policy grants it exactly the permissions it needs and nothing more.

The result is a rotation system that is auditable (the Function emits structured logs for each rotation phase to OCI Logging), recoverable (Vault retains previous secret versions for rollback), and operationally simple (rotation runs on a schedule without human intervention).

---

## 2. Goals and Non-Goals

### Goals

- Demonstrate the native Vault rotation scheduling + custom Function pattern end-to-end
- Authenticate the Function via Resource Principal (no long-lived credentials on any resource)
- Produce an audit trail that lets an operator reconstruct exactly what happened during any rotation
- Show least-privilege IAM scoping: compartment-scoped policies, narrow dynamic group matching
- Provide written artifacts (design doc, ADRs, threat model, runbook) that explain the *why* at each decision point

### Non-Goals

- Multi-region replication (discussed in [§10 — Future Work](#10-future-work); not implemented)
- Admin UI or web endpoint
- Multi-tenant isolation (single compartment is sufficient for a reference implementation)
- Exhaustive test coverage (smoke tests and key unit tests only)
- Real production target system (Object Storage demo target is sufficient to demonstrate the pattern)

---

## 3. Architecture

```mermaid
graph TD
    subgraph tenancy["Tenancy-level IAM"]
        DG1["Dynamic Group<br/>(specific Function OCID)"]
        DG2["Dynamic Group<br/>(specific Vault Secret OCID)"]
        POL["IAM Policies<br/>(compartment-scoped permissions)"]
        DG1 -. "principal matched by" .-> POL
        DG2 -. "principal matched by" .-> POL
    end

    subgraph compartment["Compartment: secret-rotation"]
        subgraph vault_group["OCI Vault"]
            KMS["KMS Master Key"]
            SEC["Secret<br/>(rotation schedule attached)"]
            KMS -- "encrypts secret material at rest" --> SEC
        end

        subgraph fn_group["OCI Functions"]
            FNA["Function App"]
            FN["rotation-handler<br/>(Python 3.12)"]
            FNA --> FN
        end

        MT["Object Storage bucket<br/>(rotation target)"]

        subgraph obs["Observability"]
            LG["OCI Logging"]
            NT["Notifications Topic<br/>(ONS)"]
        end

        SEC -- "Secret Rotation Service invokes on schedule" --> FN
        FN -- "rotates credential on" --> MT
        FN -- "writes pending/current secret version" --> SEC
        FN -- "publishes success notification" --> NT
        FN -- "emits structured logs" --> LG

        POL -. "allows Function to manage target secret by OCID" .-> SEC
        POL -. "allows Function to write target bucket" .-> MT
        POL -. "allows Function to publish to ons-topics (operation-scoped)" .-> NT
        POL -. "allows Vault Secret to invoke target Function" .-> FN

        FN -. "matched as fnfunc" .-> DG1
        SEC -. "matched as vaultsecret" .-> DG2
    end
```

### Component walkthrough

**OCI Vault + KMS key.** The Vault holds the secret and its version history. A customer-managed KMS master key encrypts secret material at rest. The secret resource carries a `rotation_config` that specifies the rotation interval and the target Function OCID — this is what drives the schedule without any custom cron infrastructure.

**OCI Function (rotation handler).** A Python 3.12 function invoked by the Vault rotation scheduler. It reads the current secret, generates a new credential, writes a pending version to Vault, updates the Object Storage target, then promotes the pending version to current. It authenticates to OCI APIs using Resource Principal. The Function is included in a narrowly scoped dynamic group by matching its OCID; OCI then issues temporary resource principal credentials to the runtime, so no user API key or static credential is stored in the code.

**Object Storage rotation target.** A private OCI Object Storage bucket that receives the new credential value on every rotation. The Function writes the credential as a named object in the bucket (`put_object`), making the result immediately observable via `oci os object get` or the Console. In a production deployment this is replaced by a call to the actual target's credential API — for example, `ALTER USER ... IDENTIFIED BY` for a database, or a vendor key-rotation endpoint for a third-party service. Only `target_client.py` changes; `rotation.py` and `vault_client.py` are target-agnostic.

**IAM dynamic groups + policies.** Two dynamic groups govern rotation. The first matches the specific Function OCID and is granted permission to manage the secret, write to the target bucket, and publish to ONS. The second matches the specific Vault Secret OCID and is granted compartment-scoped `read fn-function` plus Function-OCID-scoped `use fn-invocation` so the Vault Secret's Resource Principal can invoke only the target Function — this is the documented OCI pattern for secret rotation, where the secret resource itself holds a Resource Principal identity rather than relying on a broad service principal. All policy statements are compartment-scoped.

**OCI Logging + Notifications.** The Function emits structured JSON logs to OCI Logging on every invocation. After a successful rotation it publishes directly to an ONS topic, which delivers an email notification. OCI Events Service does not expose secret version lifecycle events — so direct publish from the Function is used instead.

---

## 4. Rotation Flow

```mermaid
sequenceDiagram
    participant VS as OCI Vault Scheduler
    participant FN as Rotation Function
    participant VW as Vault
    participant OS as Object Storage Target
    participant ONS as ONS Topic
    participant LG as OCI Logging

    VS->>FN: invoke (rotation trigger)
    FN->>VW: get_secret_bundle (read CURRENT version)
    VW-->>FN: current credential value
    FN->>FN: generate new credential
    FN->>VW: update_secret (content=<new credential>, stage=PENDING)
    VW-->>FN: PENDING version created
    FN->>VW: list_secret_versions (find version with both LATEST and PENDING stages)
    VW-->>FN: pending version number
    FN->>OS: put_object (content=<new credential>)
    OS-->>FN: credential written
    FN->>VW: update_secret (current_version_number=<pending version number>)
    VW-->>FN: version promoted to CURRENT
    FN--)LG: structured logs for each rotation phase
    FN--)ONS: publish_message (rotation complete)
    Note over VW: The CURRENT version becomes PREVIOUS (retained for rollback)
```

**Failure handling** is covered in detail in [ADR 0003](adr/0003-rotation-state-machine.md). Three partial-failure cases exist: (1) `create_pending_version` fails — target untouched, state consistent, safe to retry; (2) `update_credential` fails after the pending version is created — CURRENT unchanged, target still consistent with CURRENT, re-trigger creates a fresh pending version; (3) `promote_to_current` fails after target update — target holds the new credential but CURRENT still reflects the old one; for this Object Storage demonstration target, re-triggering recovers by overwriting the target and promoting a fresh Vault version, but real targets that require the current credential to authenticate the update may need target-specific break-glass recovery.

---

## 5. Design Decisions

### Native Vault rotation scheduling over custom cron

OCI Vault's `rotation_config` on a secret resource manages the schedule, invocation, and retry. Building a custom scheduler would require additional infrastructure (a cron job, a VM or serverless trigger, state tracking) that must itself be secured and maintained. The native scheduler is managed, audited, and zero-maintenance. See [ADR 0001](adr/0001-native-rotation-scheduler.md).

### Resource Principal for Function authentication

The Function authenticates to OCI APIs using Resource Principal — OCI issues temporary credentials to the function runtime based on its dynamic group membership, so no API keys, config files, or static credentials are stored on the Function. The IAM dynamic group rule matches the specific Function OCID, and policies grant only the permissions needed for rotation. If the Function image is compromised, the blast radius is bounded by the policy scope. See [ADR 0002](adr/0002-resource-principal-auth.md).

### Vault `DEFAULT` protection mode (software keys)

Software-protected keys are used for this reference implementation. HSM-backed (`VIRTUAL_PRIVATE`) keys provide stronger non-exportability guarantees but cost significantly more and require a dedicated HSM partition. HSM-backed keys are noted as future work in [§10 — Future Work](#10-future-work). The rotation *pattern* is identical regardless of key protection mode.

### Single compartment

Multi-compartment separation (e.g., separating the Vault from the Function) adds policy complexity without demonstrating additional patterns. A single compartment is sufficient for a reference implementation. Cross-compartment patterns are documented as future work in [§10 — Future Work](#10-future-work).

### Demo rotation target (Object Storage)

Rotating against a real database or third-party API introduces external dependencies, costs, and setup complexity that distract from the pattern being demonstrated. Instead, the Function writes the new credential value to a private OCI Object Storage object after each rotation. This makes the result immediately observable (`oci os object get` or the console) without requiring an external system.

> **This is not a production pattern.** Writing credential values to Object Storage defeats the purpose of Vault as a secrets store. In a real deployment, `target_client.py` is replaced with an implementation that calls the actual target's credential API — for example, `ALTER USER ... IDENTIFIED BY` for a database, or a vendor key-rotation endpoint for an external service. Only `target_client.py` changes; `rotation.py` and `vault_client.py` are target-agnostic.

---

## 6. Rotation State Machine

Secret versions move through the following states: `PENDING` → `CURRENT` → `PREVIOUS` → `DEPRECATED`. The Function drives the `PENDING → CURRENT` transition. The Vault automatically moves the former `CURRENT` to `PREVIOUS` when a new version is promoted.

The full state diagram — including failure handling and the re-trigger recovery path when target update fails after a pending version has been written — is in [ADR 0003](adr/0003-rotation-state-machine.md).

---

## 7. Security Model

**Trust boundaries.** The rotation Function is the only principal that crosses the boundary between the Vault (where the secret lives) and the target (where the credential is applied). This boundary crossing is governed by IAM policy on both sides.

**Authentication model.** No component holds a long-lived credential. The Function authenticates via Resource Principal — OCI issues temporary credentials to the runtime based on its dynamic group membership. The Vault Secret also authenticates via Resource Principal; its dynamic group membership grants it permission to invoke the rotation Function when the rotation schedule fires.

**Least-privilege scoping.** All policies are compartment-scoped, not tenancy-scoped. The dynamic group matches the specific Function OCID, not a broad rule like "all functions in the tenancy." If the compartment is deleted or the Function is redeployed to a new OCID, the policy stops matching — the narrowing is intentional.

**Secret version retention.** Vault retains all secret versions until explicitly pruned, up to a maximum of 30 active versions. This provides a rollback path. Soft-delete on the secret itself adds a further recovery window before permanent deletion.

**Terraform state security.** Remote state is stored in OCI Object Storage using the OCI native backend (`backend "oci"`). The backend configuration is split: non-sensitive values (bucket name, namespace, region, key path) live in `backend.hcl`, which is `.gitignore`d and never committed. The OCI native backend authenticates through `~/.oci/config` — the same API key used by the OCI Terraform provider — so no separately-managed backend credential (Customer Secret Key, access key, or service account key) is required or created.

See [docs/threat-model.md](threat-model.md) for the full STRIDE analysis.

---

## 8. Observability Model

**What is logged:**
- Every Function invocation (start, success, failure) via structured JSON to OCI Logging
- Vault API activity is available through OCI Audit (cannot be disabled)

**What is alerted:**
- The Function publishes directly to an ONS topic after each successful rotation; subscribers receive an email notification
- Function invocation failures surface in OCI Logging and can be queried or alerted on
- Note: OCI Events Service does not expose secret version lifecycle events, so event-driven notification is not used

**How to investigate:** See [docs/runbook.md](runbook.md) for exact CLI commands to query logs, list secret versions, and reconstruct the sequence of events after a rotation.

---

## 9. Operational Considerations

**Rotation cadence tradeoffs.** More frequent rotation reduces the window of exposure for a compromised credential but increases the operational load on the target system and the risk of a partial-rotation window (the period between the target being updated and Vault confirming the new version). For most use cases, 30–90 day intervals balance risk reduction against operational noise.

**Blast radius of failure.** If the Function fails after updating the target but before promoting the new Vault version to CURRENT, the target holds a new credential while Vault CURRENT still reflects the old one. For this Object Storage demonstration target, re-triggering rotation recovers by overwriting the target and promoting a fresh Vault version. Real targets that require the current credential to authenticate the update may need target-specific break-glass recovery. The recovery path is documented in the runbook.

**Rollback path.** Previous secret versions are retained in Vault. Rolling back means promoting the previous version to `CURRENT` and re-applying the old credential to the target. The runbook documents the exact steps.

---

## 10. Future Work

- **Multi-region replication.** Vault secrets can be replicated to a secondary region using OCI Vault cross-region replication. The rotation Function would need to be deployed in both regions, or a single-region Function would need to update both Vault instances. Not implemented here.
- **Cross-tenancy access.** Secrets shared across tenancies require cross-tenancy IAM policies. The pattern is documented in the OCI IAM docs but is out of scope for this reference.
- **HSM-backed keys.** Upgrading from `DEFAULT` to `VIRTUAL_PRIVATE` protection mode requires destroying and recreating the KMS key (and therefore the secret). Plan for this before using this pattern with highly sensitive material.
- **Real target integrations.** Replacing the Object Storage target with a real database (e.g., using OCI Database's password rotation API) or a third-party secret (e.g., a GitHub PAT) follows the same pattern — only `target_client.py` changes.
- **CI/CD for Function updates.** A GitHub Actions workflow that builds, pushes, and redeploys the Function on merge to `main` is a natural extension.
