# AGENTS.md — AI Collaboration Rules

**About this document.** This file defines the rules under which AI-assisted code is produced in this repository. It exists to make AI collaboration explicit, reviewable, and consistent — the same way a team would document its conventions for human contributors. The patterns here (plan-before-changes, milestone gates, credential boundaries, scope discipline) are designed to scale from solo projects like this one to team settings with additional governance layers on top.

AI assistants working in this repo should read `SPEC.md` alongside this file before proposing any changes. `SPEC.md` is the project charter; this file is the operating discipline.

---

## Core principles

1. **Plan before every action.** Before creating, modifying, or deleting any file — and before running any command that changes state (`terraform apply`, `docker push`, `git commit`, etc.) — produce a written plan in this format:

   - **What:** the specific change or action
   - **Why:** which spec requirement this addresses
   - **Files touched:** exact paths
   - **Commands to run:** exact commands
   - **Expected outcome:** what will be true after this completes

   Post the plan and wait for explicit approval ("approved", "go ahead", "proceed", or equivalent) before acting. Do not proceed on ambiguity. "Non-trivial" does not apply — every state-changing action requires a plan, including scaffolding, renaming, and deletion.

2. **Milestone gates are hard stops.** Do not proceed past a milestone boundary without explicit user confirmation. Each milestone in `SPEC.md` ends with a stop gate — honor it.

3. **Never touch credentials.** Do not ask for them, do not write them, do not log them. Credential setup is always a user action in a separate terminal. The credential gates in `SPEC.md` section 6 describe the exact prompts to use.

4. **Explain the why.** Every non-trivial decision gets a comment or doc entry explaining the rationale, not just the mechanic. Reviewers should be able to reconstruct the thinking from the artifacts alone.

5. **No scope creep.** `SPEC.md` is the contract. If something seems worth adding, flag it as a future-work item rather than building it. Out-of-scope additions are a failure mode, not a contribution.

6. **Ask when uncertain.** If the spec is ambiguous or a decision has non-obvious tradeoffs, stop and ask. Do not guess. Guessing produces work that has to be undone.

---

## Code quality rules

### Python

- Type hints on all function signatures
- Docstrings on all public functions and classes, covering purpose, arguments, return value, and side effects
- `logging` module, not `print`
- Structured log output (JSON) for consumption by OCI Logging
- No bare `except:` clauses
- No swallowing exceptions silently — errors are logged with context and re-raised or handled explicitly
- No hardcoded OCIDs, region strings, or tenancy-specific values
- No commented-out code — delete it; Git remembers

### Terraform

- Every resource has a block comment above it explaining its role and any non-default configuration
- Every IAM policy statement has an inline comment explaining what principal is granted what permission and why it's scoped that way
- Variables have `description`, `type`, and defaults where appropriate
- Modules expose a minimal, documented input/output interface
- `terraform fmt` and `terraform validate` must pass before any commit
- No hardcoded OCIDs — everything flows through variables or data sources
- Use `locals` for any value referenced more than twice

### Markdown

- Headings follow a sensible hierarchy (no jumping from h1 to h3)
- Code fences include language identifiers
- ADRs follow the Context → Decision → Consequences → Alternatives Considered format
- Documents are complete thoughts, not stubs — a partial doc is worse than an absent one

---

## Git and commit discipline

- Small, focused commits per milestone
- Commit messages follow: `<milestone>: <what changed and why>`
  - Example: `M1: add vault module with purpose comments on each resource`
- Never commit: `*.pem`, `*.key`, `*.tfstate*`, `*.tfvars`, `backend.hcl`, `.env`, `.env.local`, `.oci/`, `.terraform/`
- Verify `.gitignore` is in effect before every commit
- One logical change per commit — do not mix unrelated changes

---

## Review discipline

- Summarize what changed after each milestone: deliverables produced, acceptance criteria status, any deviations from the spec
- Surface deviations from the spec immediately — do not silently adapt
- When a milestone completes, present the summary and wait for approval before touching the next milestone
- If acceptance criteria cannot be met, stop and explain why rather than marking them met

---

## What to flag proactively

AI assistants should raise these concerns without being asked:

- Any permission that feels broader than strictly necessary
- Any retry or error-handling path that could mask silent failure
- Any OCI default that behaves differently than expected
- Any cost implication (e.g., HSM-backed keys, always-on resources, cross-region replication)
- Any place where the spec and reality have diverged during the build
- Any dependency version pin that's significantly outdated or known-vulnerable

---

## What AI assistants must not do

- Commit credentials, tokens, keys, or any material from `~/.oci/config`
- Paste or request credential material in the chat interface
- Add scope beyond what's in `SPEC.md` without explicit approval
- Mark milestones complete without verifying acceptance criteria
- Rewrite or modify ADRs after they've been marked "Accepted" — write a superseding ADR instead
- Swallow test failures or validation errors silently
- Proceed past a stop gate without user confirmation
