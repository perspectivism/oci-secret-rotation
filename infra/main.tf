# Root module — wires together all sub-modules.
#
# Module call order reflects logical dependency, not Terraform execution order
# (Terraform resolves dependencies from output/input references automatically).

# Derives the tenancy Object Storage namespace, which doubles as the OCIR registry
# namespace. Fetched from the provider so it does not need to be repeated in
# terraform.tfvars.
data "oci_objectstorage_namespace" "tenancy" {}

# Vault module — creates the KMS key, OCI Vault, and the secret.
# The secret's rotation_config block is added in M5 once the Function OCID
# is available from the function module output.
module "vault" {
  source = "./modules/vault"

  compartment_id = var.compartment_ocid
  secret_name    = var.secret_name
}

# IAM module — creates the dynamic group and rotation policies.
# function_ocid now uses the real deployed Function OCID from the function module.
module "iam" {
  source = "./modules/iam"

  tenancy_id     = var.tenancy_ocid
  compartment_id = var.compartment_ocid
  secret_name    = var.secret_name
  function_ocid  = module.function.function_id
}

# Logging module — creates the log group, custom function log, ONS topic,
# and the events rule (disabled until M6).
# notification_endpoint should be set in terraform.tfvars before M6.
module "logging" {
  source = "./modules/logging"

  compartment_id = var.compartment_ocid
}

# Network module — VCN, private subnet, and service gateway for the Function.
module "network" {
  source = "./modules/network"

  compartment_id = var.compartment_ocid
}

# Function module — OCIR repository, Function application, function, and
# invocation service log. The function image must be pushed to OCIR before
# the function can be invoked (apply can succeed before the push).
module "function" {
  source = "./modules/function"

  compartment_id    = var.compartment_ocid
  subnet_id         = module.network.subnet_id
  secret_id         = module.vault.secret_id
  log_group_id      = module.logging.log_group_id
  tenancy_namespace = data.oci_objectstorage_namespace.tenancy.namespace
  region            = var.region
  image_tag         = var.image_tag
}
