# OCI Secret Lifecycle Service — Build Specification

**About this document.** This specification was written before implementation began. It defines scope, architecture, milestones with acceptance criteria, credential handling boundaries, and written deliverables for the build of an OCI secret rotation reference implementation. It was used both as a project charter and as the instruction set for AI-assisted implementation — an example of applying spec-driven development to keep AI-assisted work reviewable, scoped, and aligned with engineering standards. The gating structure, credential boundaries, and review discipline described here are the same patterns that apply on a team, with the team governance layer (design reviews, ADR approvals, code review checklists) wrapped around them.

**Repo purpose:** Reference implementation of a production-grade secret rotation pattern on Oracle Cloud Infrastructure. Demonstrates IAM, secret management, service-to-service auth without long-lived credentials, IaC discipline, and operational readiness. Not intended for production deployment as-is.

**Scope:** Time-boxed reference implementation. The scope defined below is fixed. Do not expand beyond what is specified.

---

## 1. Project Goals

In priority order:

1. Demonstrate the canonical OCI rotation pattern: **native Vault rotation scheduling + custom Function as the rotation target**, authenticated via Resource Principal.
2. Produce written engineering artifacts (design doc, ADRs, threat model, runbook) that read as principal-level engineering output.
3. Produce clean, well-commented code that a reviewer can read top-to-bottom and understand the *why* at each step.
4. Ship something that actually works end-to-end against live OCI.

**Explicit non-goals:**
- Multi-region replication (mention in design doc, do not implement)
- Admin UI or web endpoint (out of scope)
- Multi-tenant isolation (single compartment is sufficient)
- Real production target (Object Storage stands in as a demonstrable, observable target)
- Exhaustive test coverage (smoke tests + key unit tests only)

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                       OCI Tenancy                               │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │            Compartment: secret-rotation                   │  │
│  │                                                           │  │
│  │        ┌─────────────────────────────────────────┐        │  │
│  │        │  OCI Vault Secret                       │        │  │
│  │        │  (rotation_config: schedule + fn OCID)  │        │  │
│  │        └─────────────────┬───────────────────────┘        │  │
│  │        ▲  new version    │  invokes on schedule           │  │
│  │        │  written        ▼                                │  │
│  │        │         ┌───────────────┐                        │  │
│  │        └─────────│  OCI Function │                        │  │
│  │                  │   (Python)    │                        │  │
│  │                  └─┬───────────┬─┘                        │  │
│  │                    │           │                          │  │
│  │         rotates    │           │  structured logs         │  │
│  │         credential │           │  + notifications         │  │
│  │                    ▼           ▼                          │  │
│  │   ┌──────────────────┐    ┌──────────────────────────┐    │  │
│  │   │  Object Storage  │    │  OCI Logging + ONS Topic │    │  │
│  │   │ (rotation target)│    │  (audit trail)           │    │  │
│  │   └──────────────────┘    └──────────────────────────┘    │  │
│  │                                                           │  │
│  │   IAM:                                                    │  │
│  │    • Dynamic group matching Function OCID                 │  │
│  │    • Policy: DG can manage secret-family (secret OCID)    │  │
│  │    • Policy: DG can manage objects (target bucket)        │  │
│  │    • Policy: DG can use ons-topics                        │  │
│  │    • Dynamic group matching Vault Secret OCID can         │  │
│  │      invoke Function                                      │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

**Key design decisions (to be expanded in ADRs):**

- **Native Vault rotation scheduling over custom scheduler.** Use `rotation_config` on the secret resource. Don't build a cron.
- **Resource Principal for Function auth.** No API keys on the Function. Dynamic group membership grants the permissions.
- **Python for the Function.** Fast iteration with a mature OCI SDK.
- **Single compartment.** Multi-compartment separation is out of scope for the reference implementation.
- **Object Storage as the rotation target.** The Function writes the new credential to a private Object Storage object after each rotation. This makes the result immediately observable without requiring an external system, while keeping target-specific logic isolated to `target_client.py` — swap that file to rotate a real database or API key without touching anything else.
- **OCI security-by-design patterns applied:** compartment-scoped IAM policies (not tenancy-scoped), narrow dynamic group matching (specific Function OCID), Resource Principal auth (no credentials on resources), Vault `DEFAULT` protection mode (software keys; upgrade to `VIRTUAL_PRIVATE` documented as future work if HSM is required), and soft-delete retention on secrets for accidental-deletion protection.

---

## 3. Tech Stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| IaC | Terraform with `oracle/oci` provider pinned to `~> 8.10` | Industry standard, declarative, well-supported |
| Function runtime | Python 3.12 (fnproject/python:3.12 base image) | Fast iteration, mature OCI SDK |
| Package manager | `pip` with pinned `requirements.txt` | Native fit for fnproject base image; no custom Dockerfile required |
| Container registry | OCI Container Registry (OCIR) | Native path for OCI Functions |
| Remote state | OCI Object Storage | Demonstrates team-ready IaC discipline |
| Rotation target | OCI Object Storage | Observable credential store with no external dependencies; IAM-scoped to a specific bucket |
| Local dev | Python venv, Terraform CLI, OCI CLI | Standard toolchain |
| CI (optional) | GitHub Actions workflow file, not necessarily executed | Shows the pattern |

---

## 4. Repository Structure

```
oci-secret-rotation/
├── README.md                         # Entry point, reads as design documentation
├── AGENTS.md                         # AI collaboration guardrails
├── SPEC.md                           # This document
├── docs/
│   ├── design.md                     # Full design doc
│   ├── threat-model.md               # STRIDE-style threat model
│   ├── runbook.md                    # Operational procedures
│   └── adr/
│       ├── 0001-native-rotation-scheduler.md
│       ├── 0002-resource-principal-auth.md
│       └── 0003-rotation-state-machine.md
├── infra/
│   ├── main.tf                       # Root module
│   ├── providers.tf
│   ├── variables.tf
│   ├── outputs.tf
│   ├── backend.tf                    # Remote state config
│   ├── modules/
│   │   ├── vault/                    # Vault + KMS key + secret
│   │   ├── function/                 # Function app + function resource
│   │   ├── iam/                      # Dynamic groups + policies
│   │   ├── logging/                  # Log group, ONS topic, email subscription
│   │   ├── network/                  # Private VCN, service gateway, subnet
│   │   └── target/                   # Object Storage rotation target
│   └── terraform.tfvars.example      # Example variable values (never commit real)
├── function/
│   ├── func.py                       # Handler entry point
│   ├── rotation.py                   # Rotation logic
│   ├── vault_client.py               # Vault SDK wrapper
│   ├── target_client.py              # Object Storage target client
│   ├── requirements.txt
│   ├── Dockerfile
│   ├── func.yaml                     # Fn Project config
│   └── tests/
│       └── test_rotation.py
├── scripts/
│   ├── set-env.sh                    # Populates shell env vars from terraform output
│   ├── push-image.sh                 # Builds and pushes the Function image to OCIR
│   └── destroy.sh                    # Clean teardown
└── .gitignore                        # MUST exclude *.pem, terraform.tfstate*, .terraform/, *.tfvars
```

---

## 5. Coding Conventions

### Comment philosophy

**Explain the *why*, not the *what*.** The code already shows what it does. Comments exist to explain decisions, constraints, and non-obvious context.

**Required comments:**

- **Every Terraform resource** gets a block comment above it explaining its role in the system and any non-default configuration choices.
- **Every IAM policy statement** gets a comment explaining what principal is being granted what permission and why it's scoped that way.
- **Every Python function** gets a docstring covering purpose, arguments, return value, and any side effects on Vault or the target.
- **Every non-obvious design decision** (e.g., "we use pending-then-promote instead of direct version update because...") gets a rationale comment inline.

**Avoid:**
- Comments that restate the code (`# increment i by 1`)
- Commented-out code (delete it; Git remembers)
- TODO comments without an owner or context

### Terraform conventions

- Variables have descriptions, types, and defaults where appropriate
- Resources named with `snake_case`, prefixed with the resource type's short name where helpful
- Use `locals` for any value referenced more than twice
- Modules expose a minimal, documented input/output interface
- No hardcoded OCIDs anywhere — everything flows through variables or data sources

### Python conventions

- Type hints on all function signatures
- `logging` module, not `print`
- Structured log output (JSON) for OCI Logging consumption
- Explicit error handling on all Vault and target API calls; never swallow exceptions silently
- No bare `except:` clauses

### Git hygiene

- Small, focused commits per milestone
- Commit messages follow: `<milestone>: <what changed and why>`
- Never commit: `*.pem`, `*.key`, `terraform.tfstate*`, `*.tfvars`, `.env`, `.terraform/`
- `.gitignore` is created in M0 and verified before every commit

---

## 6. Credentials and Secrets Handling

**This is the single most important operational rule.** Violate none of these.

### What the AI coding assistant must never do

- **Never** ask the user to paste credentials, private keys, API tokens, or passwords into the chat.
- **Never** write credentials to any file committed to the repo.
- **Never** echo credentials in log output or terminal output that might get copy-pasted.
- **Never** suggest storing credentials in environment variables set in the shell history.

### How credentials should flow

All OCI authentication must flow through `~/.oci/config` on the user's local machine, which the user configures themselves using the OCI CLI. Terraform and the Python SDK both read this automatically.

### Credential gates — when the AI coding assistant must stop and prompt the user

**Gate 1 (before M2 — first terraform apply):**

```
STOP. Before I can run terraform apply, you need OCI authentication configured locally.

Please run the following in a separate terminal and complete it yourself:

  oci setup config

This will prompt you for:
  - Tenancy OCID
  - User OCID
  - Region
  - It will generate an API signing keypair and write ~/.oci/config

After it completes, verify it works:

  oci iam region list

Once that returns a list of regions, let me know and we'll proceed with terraform apply.

Do NOT paste the contents of ~/.oci/config or your private key into this chat.
```

**Gate 2 (before M1.5 — remote state bootstrap):**

```
STOP. Before we initialize the Terraform backend, confirm you have created the following
in the OCI Console:

  • The Object Storage state bucket itself

Authentication for the OCI native backend (backend "oci") flows through ~/.oci/config —
the same credentials used by the OCI provider. No service user, no Customer Secret Keys,
and no separate credential management is required.

Once the bucket exists, populate backend.hcl from backend.hcl.example (bucket name,
namespace, region, and key path) and run:

  cd infra
  terraform init -backend-config=backend.hcl
```

**Gate 3 (before M4 — pushing the Function image to OCIR):**

```text
STOP. Before continuing, push the Function image to OCI Container Registry:

  bash scripts/push-image.sh

This script authenticates to OCIR via the OCI CLI, creates the repository in
the target compartment if it does not exist, builds the image, and pushes it.
Ensure infra/terraform.tfvars is populated and the OCI CLI is configured before
running it.

Do NOT paste OCIR tokens or credential material into this chat. Let me know
when the push succeeds.
```

### What goes in .gitignore (create this in M0)

```gitignore
# Credentials
*.pem
*.key
.oci/
.env
.env.local

# Terraform
.terraform/
*.tfstate
*.tfstate.*
*.tfvars
!*.tfvars.example
.terraform.lock.hcl

# Python
__pycache__/
*.pyc
.venv/
venv/
.pytest_cache/

# OS
.DS_Store
Thumbs.db
```

---

## 7. Milestones

**Gating rule: at the end of every milestone, the AI coding assistant stops and summarizes what was completed, what the acceptance criteria showed, and asks for explicit approval to proceed to the next milestone.** Do not proceed without user confirmation.

### M0 — Scaffolding and design doc draft (no credentials needed)

**Prerequisites:** `SPEC.md` and `AGENTS.md` already committed to the repo root. the AI coding assistant must have read both before proposing the M0 plan.

**Goal:** Repo skeleton and written plan exist before any code.

**Deliverables:**
- Repo directory structure per section 4
- `.gitignore` per section 6
- `README.md` skeleton with section headers, including a Mermaid architecture diagram (placeholder acceptable at this stage; finalized in M7)
- `docs/design.md` first draft: problem statement, architecture (with Mermaid diagram placeholder), design decisions, explicit non-goals, future work
- Empty ADR files with titles and status lines, including `0003-rotation-state-machine.md` reserved for the Mermaid state diagram added in M7

**Acceptance criteria:**
- Directory tree matches spec
- Design doc is a readable 1–2 page document, not a stub
- `.gitignore` explicitly excludes all credential patterns

**Stop gate:** Present the design doc to user for review. Revise based on feedback before proceeding.

---

### M1 — Terraform foundation, offline validation only

**Goal:** All Terraform code written and validated locally. No `apply` yet.

**Deliverables:**
- `providers.tf` with OCI provider pinned to a specific version
- `variables.tf` with inputs: `tenancy_ocid`, `user_ocid`, `region`, `compartment_ocid`, `secret_name`, `rotation_interval_days`
- `modules/vault/` implementing: KMS key, Vault, Secret (rotation config stubbed for now)
- `modules/iam/` implementing: dynamic group, policies (placeholders until Function exists)
- `modules/logging/` implementing: log group, log, events subscription stubs
- `terraform.tfvars.example` with documented placeholder values
- `backend.tf` with Object Storage backend configured (not initialized yet)

**Acceptance criteria:**
- `terraform fmt -check` passes
- `terraform validate` passes in every module
- Every resource has a purpose comment
- Every policy statement has a justification comment

**Stop gate:** Show the user the policy statements specifically and confirm they're scoped correctly before moving on. This is the highest-risk area for mistakes.

---

### M1.5 — Credential setup + remote state bootstrap

**Goal:** User has OCI CLI configured and remote state bucket ready.

**Deliverables:**
- User completes OCI CLI setup per Gate 1
- User creates Object Storage bucket per Gate 2
- `backend.hcl` populated from `backend.hcl.example` with real bucket name, namespace, and region
- `terraform init -backend-config=backend.hcl` succeeds

**Acceptance criteria:**
- `oci iam region list` returns regions from the user's terminal
- `terraform init -backend-config=backend.hcl` reports successful backend initialization

**Stop gate:** Confirm with user that init succeeded before applying.

---

### M2 — First terraform apply (credentials active)

**Goal:** Vault, KMS key, secret (without rotation target yet), dynamic group placeholder, and logging infrastructure exist in OCI.

**Deliverables:**
- `terraform plan` reviewed with user (show the plan output, explain what will be created)
- `terraform apply` executes successfully
- Resources verified via OCI Console or CLI

**Acceptance criteria:**
- `oci vault vault list --compartment-id <id>` returns the new vault
- `oci secrets secret-bundle get --secret-id <id>` returns the secret (with placeholder content)
- No resources in unexpected states

**Stop gate:** User confirms resources look correct in console before proceeding.

---

### M3 — Function code

**Goal:** Rotation Function written, tested locally with mocks, not yet deployed.

**Deliverables:**
- `function/func.py`: handler entry point with structured logging
- `function/rotation.py`: rotation state machine (pending → current → retire old)
- `function/vault_client.py`: Vault SDK wrapper with explicit error handling
- `function/target_client.py`: mock target client — rotates credentials against an in-memory store or an Object Storage object
- `function/tests/test_rotation.py`: unit tests covering happy path, target-update-fails-after-vault-write, and Vault-write-fails paths
- `function/Dockerfile` using the official fnproject Python base image
- `function/func.yaml` with correct schema version and config

**Acceptance criteria:**
- `pytest` passes
- `docker build` succeeds
- Code has full docstrings and type hints
- Rotation state machine handles the three failure modes documented in the threat model

**Stop gate:** Walk through the rotation state machine with user. The design must be defensible, including the specific behavior when the target update fails after the Vault write succeeds.

---

### M4 — Function deployment

**Goal:** Function deployed to OCI, invokable manually.

**Deliverables:**
- User completes OCIR auth per Gate 3
- Image built and pushed to OCIR
- Terraform updated: `modules/function/` now references the pushed image
- `terraform apply` deploys the Function app and function
- Manual invocation via `oci fn function invoke` succeeds and writes a log entry

**Acceptance criteria:**
- Function appears in OCI Console
- Manual invocation returns success
- Function execution log visible in OCI Logging

**Stop gate:** Confirm invocation works end-to-end before wiring rotation.

---

### M5 — Wire up rotation

**Goal:** Vault's native rotation scheduler invokes the Function; new secret versions are created automatically and the credential is observable in a real OCI target.

**Deliverables:**
- Secret resource updated with `rotation_config` targeting the Function OCID
- Dynamic group rule updated to match the deployed Function's OCID
- Policies finalized:
  - Dynamic group can `manage secret-family` in compartment
  - Dynamic group can `manage objects` in the target bucket
  - Dynamic group matched to the specific Vault Secret OCID can invoke the Function
- Object Storage bucket provisioned as the rotation target (simulates a credential store)
- `ObjectStorageTargetClient` implemented — `update_credential` writes the new credential value to a known object in the bucket
- Function config updated with bucket name, namespace, and object name
- `MockTargetClient` replaced by `ObjectStorageTargetClient` in `func.py`
- Manual rotation trigger (`oci vault secret rotate`) executes successfully
- New secret version created; target object in Object Storage reflects new credential

**Acceptance criteria:**
- `oci vault secret list-versions` shows the new version
- `oci os object get` on the target object returns the new credential value
- OCI Logging captures the rotation event

**Stop gate:** Verify the full flow with user. This is the core demonstration of the system.

---

### M6 — Observability and audit trail

**Goal:** Rotation events produce a clear, queryable audit trail.

**Deliverables:**
- Rotation Function publishes directly to ONS topic after each successful rotation
  (OCI Events Service does not expose secret version lifecycle events; direct publish is more reliable)
- ONS email subscription confirmed and receiving rotation notifications
- IAM policy restricting the Function's ONS publish permission to the `PublishMessage` operation across ons-topics in the compartment (per-topic OCID scoping is not supported by OCI IAM for ons-topics)
- Log search queries documented in runbook
- Verification: trigger another rotation, confirm email received, OCI Logging entry visible

**Acceptance criteria:**
- Email notification arrives after `oci vault secret rotate`
- OCI Logging shows the structured rotation log entry
- Runbook contains the exact CLI commands to verify each step

**Stop gate:** Demo the full audit trail to user.

---

### M7 — Written artifacts completion

**Goal:** All written deliverables are reviewer-ready.

**Deliverables:**
- `docs/design.md`: full design doc with two Mermaid diagrams — (a) a detailed **architecture diagram** showing components, boundaries, and data flow, and (b) a **rotation sequence diagram** showing the end-to-end flow of a rotation event from scheduler trigger through audit log emission. Design decisions, tradeoffs, and future work section covering multi-region and cross-tenancy.
- `docs/adr/0001-native-rotation-scheduler.md`: why native scheduling over custom cron; when you'd deviate
- `docs/adr/0002-resource-principal-auth.md`: why Resource Principals; alternatives considered
- `docs/adr/0003-rotation-state-machine.md`: `PENDING`/`CURRENT`/`PREVIOUS`/`DEPRECATED` lifecycle and why, including a Mermaid **state diagram** showing transitions and failure handling (re-trigger recovery on target update failure)
- `docs/threat-model.md`: STRIDE analysis covering rotation Function compromise, Vault access compromise, target system compromise, partial-rotation failure, replay attacks
- `docs/runbook.md`: operational procedures for manual rotation, rollback to previous version, failure investigation, secret version pruning, full destroy
- `README.md`: polished, with a simplified Mermaid **architecture diagram** above the fold (before the quickstart), quickstart instructions, and links to the design doc and ADRs

**Acceptance criteria:**
- A reviewer can read the README and understand the project in 5 minutes
- A reviewer can read the design doc and understand the tradeoffs in 15 minutes
- Every ADR follows a consistent format: Context → Decision → Consequences → Alternatives Considered
- All four Mermaid diagrams render correctly on GitHub: README architecture, design-doc architecture, rotation sequence, and rotation state
- Architecture diagram in README matches the more detailed version in `docs/design.md` — same components, same relationships, just with less detail

**Stop gate:** Review all written artifacts with user.

---

### M8 — Final polish and handoff

**Goal:** Repo is ready for a reviewer to clone and read.

**Deliverables:**
- Final `terraform fmt` pass
- Final `pytest` pass
- README updated with any last corrections
- Screen recording (optional, 2–3 minutes) of the rotation firing end-to-end
- `scripts/destroy.sh` verified to cleanly tear down all resources
- User decides: keep resources running for live demonstration (at cost), or destroy and rely on code + recording

**Acceptance criteria:**
- A fresh `git clone` + `terraform apply` works with nothing but `~/.oci/config` and a variables file
- No credentials anywhere in the repo
- No stray debug code or commented-out blocks

**Stop gate:** Final handoff. User signs off.

---

## 8. Written Artifact Specifications

### Design doc (`docs/design.md`)

Required sections, in order:

1. **Problem statement** — what this system does and why rotation matters
2. **Goals and non-goals** — explicit scope boundaries
3. **Architecture** — Mermaid architecture diagram + prose walkthrough of components and boundaries
4. **Rotation flow** — Mermaid sequence diagram showing the end-to-end rotation: scheduler trigger, Function invocation, target update, Vault version write, audit log emission
5. **Design decisions** — key choices with rationale
6. **Rotation state machine** — `PENDING` → `CURRENT` → `PREVIOUS` → `DEPRECATED` lifecycle, with failure handling and re-trigger recovery; reference ADR 0003 for the state diagram
7. **Security model** — trust boundaries, authentication model, least-privilege scoping
8. **Observability model** — what's logged, what's alerted, how to investigate
9. **Operational considerations** — rotation cadence tradeoffs, blast radius of failure, rollback path
10. **Future work** — multi-region, cross-tenancy, target system integrations, CI/CD for Function updates

### Threat model (`docs/threat-model.md`)

STRIDE-style analysis covering at minimum:

- **Spoofing:** What prevents an unauthorized principal from invoking the rotation Function?
- **Tampering:** What prevents modification of secret material in transit or at rest?
- **Repudiation:** How do we prove a rotation occurred and who triggered it?
- **Information disclosure:** What prevents credential leakage via logs, errors, or version history?
- **Denial of service:** What happens if the Function is rate-limited or Vault is unavailable?
- **Elevation of privilege:** What prevents the Function from accessing secrets outside its scope?

Also cover rotation-specific failure modes:
- Function rotates target but fails to write new version to Vault
- Function writes new version to Vault but fails to update target
- Duplicate concurrent rotation invocations
- Replay of old rotation triggers

Each threat identified must name the specific OCI primitive that mitigates it (e.g., Resource Principals prevent credential theft; compartment-scoped policies limit blast radius; Vault soft-delete retention protects against malicious deletion; OCI Audit captures every API call for forensic reconstruction). A generic mitigation ("use strong authentication") is not sufficient — the mitigation must reference the specific OCI service or feature that enforces it.

### Runbook (`docs/runbook.md`)

Required procedures, each with exact CLI commands:

- Trigger manual rotation
- List secret versions and identify current version
- Roll back to a previous version (promote old, retire current)
- Investigate a failed rotation (log query, common causes)
- Prune old secret versions
- Update the Function code (build, push, redeploy)
- Full teardown

### ADRs (`docs/adr/*.md`)

Each ADR follows this format:

```markdown
# ADR NNNN: <Title>

**Status:** Accepted | Superseded | Deprecated
**Date:** YYYY-MM-DD

## Context
<Why is this decision being made? What constraints apply?>

## Decision
<What was decided?>

## Consequences
<What becomes easier? What becomes harder? What new risks?>

## Alternatives Considered
<What other options were evaluated and why were they rejected?>
```

### Diagrams (Mermaid)

All diagrams are authored in Mermaid and embedded directly in the relevant markdown files so they render natively on GitHub. No PNGs, no external diagrams.net files. If a diagram would require more than about ten nodes or eight sequence participants to express, split it into multiple focused diagrams rather than one crowded one.

Four required diagrams (the architecture diagram appears in two files — a simplified version in README and a detailed version in design.md):

**1. Architecture diagram — `README.md` (simplified) and `docs/design.md` (detailed).**
A static component view showing Vault, the rotation Function, the target system, logging/events, and the IAM relationships (dynamic group, policies). The README version stays high-level; the design doc version shows compartment boundaries, subnet topology if relevant, and the specific IAM principals involved. Both versions must show the same components and relationships — a reviewer should not find contradictions between them.

**2. Rotation sequence diagram — `docs/design.md`.**
A Mermaid `sequenceDiagram` showing the end-to-end flow of a rotation event: Vault scheduler triggers, Function is invoked, Function reads the current secret, Function writes the new version to Vault as `PENDING`, Function provisions a new credential on the target, Function promotes `PENDING` to `CURRENT`, Function publishes a notification to the ONS topic. Include notes on retained previous versions for rollback.

**3. Rotation state diagram — `docs/adr/0003-rotation-state-machine.md`.**
A Mermaid `stateDiagram-v2` showing secret version states (`PENDING`, `CURRENT`, `PREVIOUS`, `DEPRECATED`) and transitions, including failure handling and the re-trigger recovery path when target update fails after a pending version is written. This is where the distributed-systems reasoning becomes visually explicit.

Diagrams are first-class deliverables, not decoration. They must match the deployed reality at project close — if the implementation deviates from the original diagram, update the diagram, don't paper over the mismatch.

---

## 9. Final Review Checklist

Before declaring the project complete, verify every item:

- [ ] `git status` shows a clean working tree
- [ ] `.gitignore` excludes all credential patterns
- [ ] `grep -ri "ocid1\." --include="*.tf" --include="*.py" --include="*.md"` returns no hardcoded OCIDs outside of `.tfvars.example` and docs
- [ ] `grep -ri "password\|secret\|token\|key" --include="*.tf" --include="*.py"` returns only legitimate variable names, no values
- [ ] `terraform fmt -check -recursive` passes
- [ ] `terraform validate` passes in every module
- [ ] `pytest` passes with no skipped tests
- [ ] `docker build` produces a working image
- [ ] README walkthrough reproduces the build from scratch
- [ ] Every milestone's acceptance criteria were explicitly verified
- [ ] All ADRs have status "Accepted" (not "Proposed")
- [ ] All four Mermaid diagrams render correctly on GitHub (architecture in README + design doc, sequence in design doc, state in ADR 0003)
- [ ] Architecture diagrams in README and design doc are consistent — same components, same relationships
- [ ] Design doc architecture diagram matches deployed reality
- [ ] Runbook commands have been tested, not just written
