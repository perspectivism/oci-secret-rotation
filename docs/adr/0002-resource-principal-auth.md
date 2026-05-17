# ADR 0002: Use Resource Principal for Function Authentication

**Status:** Accepted
**Date:** 2026-05-16

## Context

The rotation Function must authenticate to OCI APIs at runtime — reading secret versions from Vault, creating and promoting versions, writing the credential to Object Storage, and publishing a notification to ONS. Every one of these calls requires a signed OCI identity.

Three options were evaluated:

- **Resource Principal** — the Function authenticates using its own OCID as the credential, mediated by the OCI Resource Principal service built into the Functions runtime
- **API key stored in Function config** — a user-owned API key is stored as a plaintext value in the Function application's config map
- **Credentials hard-coded in the container image** — credentials baked into the Dockerfile at build time

## Decision

Use Resource Principal. The Function's OCID is enrolled in an IAM dynamic group via a matching rule that binds both the resource type (`fnfunc`) and the specific OCID. IAM policies grant that dynamic group exactly the permissions required for rotation.

```python
signer = oci.auth.signers.get_resource_principals_signer()
client = SecretsClient(config={}, signer=signer)
```

The dynamic group matching rule:

```
ALL {resource.type = 'fnfunc', resource.id = '<function-ocid>'}
```

Using `ALL{}` with both conditions is intentional: the Function must be both the right resource type and the specific OCID. A rule matching only by compartment or only by resource type would enroll every Function deployed there — an unacceptable blast radius.

## Consequences

**Easier:**
- No credential to rotate, store, manage, or accidentally commit — the Function's own OCI identity is the credential
- Blast radius of a compromised Function image is bounded by IAM policy scope. An attacker who exfiltrates the image gains no credential material — Resource Principal only works when code executes inside the specific OCI Function OCID
- Every API call carries the Function's OCID as the caller identity in OCI Audit, providing a precise and unforgeable trail
- The credential cannot expire, cannot be stolen out of config, and requires no separate rotation cycle

**Harder:**
- Requires correct dynamic group configuration before any API call will succeed. A misconfigured matching rule causes silent `401` authentication failures that can be difficult to distinguish from permission errors
- If the Function resource is destroyed and recreated (new OCID), Terraform must update the dynamic group matching rule before the replacement Function can authenticate
- Local development and unit tests cannot use Resource Principal. `VaultClient` accepts an explicit `signer` argument specifically to allow injection of a config-file signer or mock signer during testing

## Alternatives Considered

**API key in Function config:** A user-owned API key stored as a plaintext config variable is visible in the OCI Console and via API to any IAM principal with `read fn-application`. The key must be rotated on a separate schedule, and that rotation is not automated — exactly the class of credential management problem the rotation system exists to eliminate. If the Function config is read by an attacker, the key provides persistent access until manually revoked.

**Credentials hard-coded in the container image:** Credentials in a Dockerfile layer persist in image layer history even after "removal" via a subsequent `RUN` command. They are accessible to anyone who can pull the image from OCIR. They cannot be rotated without rebuilding and redeploying the image. This option creates permanent credential exposure with no recovery path short of rotating the credential and rebuilding every image layer that touched it.

**OCI Instance Principal:** Designed for Compute instances, not Functions. Functions use the Resource Principal model, which is the correct authentication mechanism for OCI serverless workloads. Using Instance Principal would require attaching the Function to a Compute instance, defeating the serverless deployment model and introducing a persistent compute cost.
