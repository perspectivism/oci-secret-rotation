# Creates a dynamic group whose sole member is the rotation Function.
#
# Dynamic groups are tenancy-level resources — compartment_id must be the tenancy
# OCID, not the application compartment. The group itself has no permissions;
# those are granted by the policy below.
#
# The matching rule uses ALL{} with both resource.type and resource.id, which is
# the narrowest possible match: only the specific Function OCID is included.
# A broader rule (e.g. matching all fnfunc resources in a compartment) would
# grant rotation permissions to any Function deployed there — an unacceptable
# blast radius. See ADR 0002 for the full rationale.
resource "oci_identity_dynamic_group" "rotation_function" {
  compartment_id = var.tenancy_id
  name           = var.dynamic_group_name
  description    = "Grants the secret rotation Function a Resource Principal identity. Matched by specific Function OCID only — see matching_rule."

  matching_rule = "ALL {resource.type = 'fnfunc', resource.id = '${var.function_ocid}'}"
}

# Creates a dynamic group whose sole member is the rotation Vault Secret.
#
# OCI's documented pattern for automatic secret rotation uses a resource principal
# for the vault secret itself — not the vaultsecret service principal. This group
# is matched by both resource type and the specific secret OCID so that only this
# secret can invoke the rotation Function; any other vault secret in the tenancy
# is excluded even if it also has a rotation_config attached.
resource "oci_identity_dynamic_group" "rotation_secret" {
  compartment_id = var.tenancy_id
  name           = var.vault_secret_dynamic_group_name
  description    = "Grants the rotation Vault Secret a resource principal identity so it can invoke the rotation Function on schedule. Matched by specific secret OCID only."

  matching_rule = "ALL {resource.type = 'vaultsecret', resource.id = '${var.secret_id}'}"
}

# Grants the Function and Vault Secret resource principals the permissions
# needed to execute a rotation end-to-end.
#
# This policy is created in the application compartment, not the tenancy root.
# Compartment-scoped policies limit the effect of any misconfiguration to this
# compartment and its children only.
resource "oci_identity_policy" "rotation" {
  compartment_id = var.compartment_id
  name           = var.policy_name
  description    = "Permits the rotation Function to manage secret versions, write to the target bucket, and publish notifications. Permits the Vault Secret resource principal to invoke the rotation Function on schedule."

  statements = [
    # Grants the rotation Function permission to read the current secret value
    # and to create and promote new secret versions (PENDING → CURRENT).
    # The 'where' condition pins this to a single secret OCID — the Function
    # cannot manage any other secret in the compartment even if the dynamic
    # group matching rule were ever broadened. OCID is used over name because
    # it cannot drift if the secret is deleted and recreated with the same name.
    "Allow dynamic-group ${oci_identity_dynamic_group.rotation_function.name} to manage secret-family in compartment id ${var.compartment_id} where target.secret.id = '${var.secret_id}'",

    # Grants the vault secret resource principal permission to look up and invoke
    # the rotation Function when the rotation_config schedule fires.
    # 'read fn-function' lets the secret resolve the Function endpoint —
    # this is compartment-scoped only, not pinned to a specific Function OCID.
    # 'use fn-invocation' lets it send the invocation request, scoped to the
    # specific Function OCID so no other function in the compartment can be invoked.
    # Both are required: without read, the scheduler cannot locate the Function;
    # without use, OCI rejects the invocation even if the endpoint is known.
    "Allow dynamic-group ${oci_identity_dynamic_group.rotation_secret.name} to read fn-function in compartment id ${var.compartment_id}",
    "Allow dynamic-group ${oci_identity_dynamic_group.rotation_secret.name} to use fn-invocation in compartment id ${var.compartment_id} where target.function.id = '${var.function_ocid}'",

    # Grants the rotation Function permission to create or overwrite the credential
    # object in the target bucket. manage objects is required because the first
    # rotation uses OBJECT_CREATE (object does not yet exist) and subsequent
    # rotations use OBJECT_OVERWRITE — use objects covers only the latter.
    # Tradeoff: manage objects also grants delete, restore, and tier-update on
    # objects in this bucket. Acceptable here because the bucket holds only the
    # rotation target object and access is already compartment- and bucket-scoped.
    "Allow dynamic-group ${oci_identity_dynamic_group.rotation_function.name} to manage objects in compartment id ${var.compartment_id} where target.bucket.name = '${var.target_bucket_name}'",

    # Grants the rotation Function permission to publish messages to ONS topics
    # in this compartment so it can send a notification after each successful rotation.
    # 'where request.operation = PublishMessage' restricts this to the publish operation
    # only — the Function never needs to manage subscriptions or topic metadata.
    # Note: OCI IAM does not appear to support per-topic target conditions (e.g.
    # target.ons.topicId) for ons-topics. Further investigation and testing is needed
    # to determine whether permissions can be tightened to the specific rotation topic.
    "Allow dynamic-group ${oci_identity_dynamic_group.rotation_function.name} to use ons-topics in compartment id ${var.compartment_id} where request.operation = 'PublishMessage'",
  ]
}
