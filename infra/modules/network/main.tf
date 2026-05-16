terraform {
  required_providers {
    oci = {
      source = "oracle/oci"
    }
  }
}

# Looks up the "All <region> Services In Oracle Services Network" service CIDR label.
# This covers supported regional OCI service API endpoints reachable through a
# Service Gateway, including Vault, Secret Management/Retrieval, Object Storage,
# Functions, Notifications, Logging, and OCIR.
data "oci_core_services" "all_oci_services" {
  filter {
    name   = "name"
    values = ["All .* Services In Oracle Services Network"]
    regex  = true
  }
}

# VCN that contains all rotation infrastructure. A single CIDR block is
# sufficient — only one private subnet is needed for the Function application.
resource "oci_core_vcn" "rotation" {
  compartment_id = var.compartment_id
  cidr_blocks    = [var.vcn_cidr]
  display_name   = "secret-rotation-vcn"
  dns_label      = "rotationvcn"
}

# Service Gateway routes outbound OCI API traffic (Vault, Secrets) directly over
# Oracle's backbone network without traversing the public internet. The rotation
# Function does not need public internet egress for this implementation because all
# its dependencies are OCI services reachable through the Service Gateway. If the
# production target is an external API or SaaS endpoint, add a NAT Gateway or
# other approved egress path — no Internet Gateway is created here.
resource "oci_core_service_gateway" "rotation" {
  compartment_id = var.compartment_id
  vcn_id         = oci_core_vcn.rotation.id
  display_name   = "secret-rotation-sgw"

  services {
    service_id = data.oci_core_services.all_oci_services.services[0].id
  }
}

# Route table for the private subnet. The single rule sends all Oracle Services
# Network traffic to the Service Gateway — all other destinations are unreachable,
# which enforces the no-internet-egress constraint at the routing layer.
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

# Security list for the private subnet. Only outbound HTTPS to Oracle Services
# Network is permitted — no ingress rules and no other egress destinations.
resource "oci_core_security_list" "private" {
  compartment_id = var.compartment_id
  vcn_id         = oci_core_vcn.rotation.id
  display_name   = "secret-rotation-private-sl"

  # Stateful HTTPS egress to supported OCI service endpoints via the Service Gateway.
  # Stateful means return traffic is automatically permitted — no ingress rule needed
  # for API responses. protocol "6" = TCP.
  # This is intentionally narrower than Oracle's Functions subnet example, which allows
  # all protocols to the Oracle Services Network. TCP/443 is sufficient for this
  # implementation's HTTPS-based OCI API calls and has been verified with Functions
  # cold start, OCIR image pull, Vault, Object Storage, Logging, and ONS.
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
