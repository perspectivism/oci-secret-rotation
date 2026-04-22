output "subnet_id" {
  description = "OCID of the private subnet. Passed to the Function application resource as its subnet_ids value."
  value       = oci_core_subnet.private.id
}

output "vcn_id" {
  description = "OCID of the VCN. Available for reference and for adding further subnets or gateways in future milestones."
  value       = oci_core_vcn.rotation.id
}
