# Looks up the "All <region> Services In Oracle Services Network" CIDR block.
# This single entry covers all OCI service endpoints (Vault, Secrets, Functions,
# Object Storage, etc.) and is the correct destination for Service Gateway routes.
data "oci_core_services" "all_oci_services" {
  filter {
    name   = "name"
    values = ["All .* Services In Oracle Services Network"]
    regex  = true
  }
}

resource "oci_core_vcn" "rotation" {
  compartment_id = var.compartment_id
  cidr_blocks    = [var.vcn_cidr]
  display_name   = "secret-rotation-vcn"
  dns_label      = "rotationvcn"
}

# Service Gateway routes outbound OCI API traffic (Vault, Secrets) directly over
# Oracle's backbone network. The rotation Function never needs to reach the internet,
# so no NAT gateway or internet gateway is created. This is the minimal egress
# required for the function to operate.
resource "oci_core_service_gateway" "rotation" {
  compartment_id = var.compartment_id
  vcn_id         = oci_core_vcn.rotation.id
  display_name   = "secret-rotation-sgw"

  services {
    service_id = data.oci_core_services.all_oci_services.services[0].id
  }
}

resource "oci_core_route_table" "private" {
  compartment_id = var.compartment_id
  vcn_id         = oci_core_vcn.rotation.id
  display_name   = "secret-rotation-private-rt"

  route_rules {
    destination       = data.oci_core_services.all_oci_services.services[0].cidr_block
    destination_type  = "SERVICE_CIDR_BLOCK"
    network_entity_id = oci_core_service_gateway.rotation.id
  }
}

resource "oci_core_security_list" "private" {
  compartment_id = var.compartment_id
  vcn_id         = oci_core_vcn.rotation.id
  display_name   = "secret-rotation-private-sl"

  # Stateful HTTPS egress to OCI service endpoints via the service gateway.
  # Stateful means return traffic is automatically permitted — no ingress rule needed
  # for API responses. protocol "6" = TCP.
  egress_security_rules {
    destination      = data.oci_core_services.all_oci_services.services[0].cidr_block
    destination_type = "SERVICE_CIDR_BLOCK"
    protocol         = "6"
    stateless        = false

    tcp_options {
      min = 443
      max = 443
    }
  }
}

# Private regional subnet — no public IPs assigned to any VNIC in this subnet.
# Functions deployed here can only reach destinations reachable via the route table
# (OCI services via the service gateway). All other outbound traffic is dropped.
resource "oci_core_subnet" "private" {
  compartment_id             = var.compartment_id
  vcn_id                     = oci_core_vcn.rotation.id
  cidr_block                 = var.subnet_cidr
  display_name               = "secret-rotation-private-subnet"
  dns_label                  = "rotation"
  prohibit_public_ip_on_vnic = true
  route_table_id             = oci_core_route_table.private.id
  security_list_ids          = [oci_core_security_list.private.id]
}
