# Private Object Storage bucket that acts as the rotation target.
#
# In a real deployment the target would be a database, API gateway, or
# application config store. Object Storage is used here as a demo stand-in:
# it receives the new credential on every rotation and the change is
# immediately observable via the console or CLI. See docs/design.md §Demo
# for the production target discussion.
#
# access_type = "NoPublicAccess" blocks all unauthenticated requests.
# Only principals granted explicit IAM policies can read or write objects.
resource "oci_objectstorage_bucket" "target" {
  compartment_id = var.compartment_id
  namespace      = var.namespace
  name           = var.bucket_name
  access_type    = "NoPublicAccess"
}
