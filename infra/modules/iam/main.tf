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

  # Both conditions must match: resource must be a Function AND must have
  # the specific OCID of the rotation Function. Update function_ocid in M5.
  matching_rule = "ALL {resource.type = 'fnfunc', resource.id = '${var.function_ocid}'}"
}

# Grants the dynamic group and the Vault scheduler service the permissions
# needed to execute a rotation end-to-end.
#
# This policy is created in the application compartment, not the tenancy root.
# Compartment-scoped policies limit the effect of any misconfiguration to this
# compartment and its children only.
resource "oci_identity_policy" "rotation" {
  compartment_id = var.compartment_id
  name           = var.policy_name
  description    = "Permits the rotation Function to manage secret versions and permits the Vault service to invoke the Function on the rotation schedule."

  statements = [
    # Grants the rotation Function permission to read the current secret value
    # and to create and promote new secret versions (PENDING → CURRENT).
    # The 'where' condition pins this to a single named secret — the Function
    # cannot manage any other secret in the compartment even if the dynamic
    # group matching rule were ever broadened.
    "Allow dynamic-group ${oci_identity_dynamic_group.rotation_function.name} to manage secret-family in compartment id ${var.compartment_id} where target.secret.name = '${var.secret_name}'",

    # Grants the OCI Vault scheduler service permission to look up and invoke
    # the rotation Function when the rotation_config schedule fires.
    # 'read fn-function' lets the service resolve the Function endpoint;
    # 'use fn-invocation' lets it send the invocation request.
    # Both are required: without read, the scheduler cannot locate the Function;
    # without use, OCI rejects the invocation even if the endpoint is known.
    "Allow service vaultsecret to read fn-function in compartment id ${var.compartment_id}",
    "Allow service vaultsecret to use fn-invocation in compartment id ${var.compartment_id}",

    # Grants the rotation Function permission to write the new credential to the
    # Object Storage target bucket. Scoped to the specific bucket by name so the
    # Function cannot access any other bucket in the compartment.
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
