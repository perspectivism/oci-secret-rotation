# Root module — wires together the vault, iam, and logging sub-modules.
#
# Module call order reflects logical dependency, not Terraform execution order
# (Terraform resolves dependencies from output/input references automatically).
# The function module is absent here; it is added in M4 once the Function image
# exists in OCIR and has a stable OCID to reference.

# Vault module — creates the KMS key, OCI Vault, and the secret.
# The secret's rotation_config block is added in M5 once the Function OCID
# is available from the function module output.
module "vault" {
  source = "./modules/vault"

  compartment_id = var.compartment_ocid
  secret_name    = var.secret_name
}

# IAM module — creates the dynamic group and rotation policies.
# function_ocid defaults to a placeholder in the module; it is overridden here
# in M5 using module.function.function_ocid once that module exists.
module "iam" {
  source = "./modules/iam"

  tenancy_id     = var.tenancy_ocid
  compartment_id = var.compartment_ocid
  secret_name    = var.secret_name
}

# Logging module — creates the log group, custom function log, ONS topic,
# and the events rule (disabled until M6).
# notification_endpoint should be set in terraform.tfvars before M6.
module "logging" {
  source = "./modules/logging"

  compartment_id = var.compartment_ocid
}

# -----------------------------------------------------------------------
# M4 placeholder: function module call goes here once the Function image
# is pushed to OCIR and modules/function/ is implemented.
#
# module "function" {
#   source = "./modules/function"
#
#   compartment_id            = var.compartment_ocid
#   log_group_id              = module.logging.log_group_id
#   function_log_id           = module.logging.function_log_id
#   ...
# }
# -----------------------------------------------------------------------
