variable "compartment_id" {
  description = "OCID of the compartment in which the VCN and all network resources are created."
  type        = string
}

variable "vcn_cidr" {
  description = "CIDR block for the VCN."
  type        = string
  default     = "10.0.0.0/16"
}

variable "subnet_cidr" {
  description = "CIDR block for the private subnet. Must be within vcn_cidr."
  type        = string
  default     = "10.0.1.0/24"
}
