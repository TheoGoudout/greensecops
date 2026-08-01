output "volume_id" {
  description = "ID of the state volume. Instances discover it by tag rather than by ID, so this is for operators and for restore procedures."
  value       = aws_ebs_volume.state.id
}

output "availability_zone" {
  description = "Zone the volume — and therefore the host group that mounts it — is pinned to."
  value       = aws_ebs_volume.state.availability_zone
}

output "discovery_tag" {
  description = "Tag key/value cloud-init matches on to find and attach the volume at boot."
  value = {
    key   = "greensecops:state-volume"
    value = var.name_prefix
  }
}
