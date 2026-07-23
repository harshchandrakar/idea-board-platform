# Conftest/OPA policy — gate 4 of the validation gauntlet (Part C).
# Runs in CI against `terraform show -json plan`. Blocks off-policy infrastructure.
package main

# Deny a publicly accessible managed database.
deny[msg] {
  rc := input.resource_changes[_]
  rc.type == "aws_db_instance"
  rc.change.after.publicly_accessible == true
  msg := sprintf("database %v must not be publicly accessible", [rc.address])
}

# Deny more nodes than policy allows (example: desired_size on an EKS node group).
deny[msg] {
  rc := input.resource_changes[_]
  rc.change.after.scaling_config[_].desired_size > 6
  msg := sprintf("%v exceeds max_node_count (6)", [rc.address])
}

# Require standard tags on taggable resources.
deny[msg] {
  rc := input.resource_changes[_]
  tags := rc.change.after.tags
  not tags.env
  msg := sprintf("%v is missing required tag: env", [rc.address])
}
