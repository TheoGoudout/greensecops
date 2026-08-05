# METADATA
# title: EBS volume uses the superseded gp2 type
# description: A volume is declared as gp2, which gp3 replaced. gp3 costs about 20% less per GB, delivers 3000 IOPS and 125 MB/s at any size, and lets throughput be set independently of capacity — whereas gp2 ties performance to size, so the usual way to make a gp2 volume fast enough is to over-provision capacity nobody needs. That over-provisioning is storage that is manufactured, powered and paid for to buy IOPS.
# custom:
#   severity: low
#   detection: static_analysis
#   examples:
#     bad: |
#       resource "aws_ebs_volume" "data" {
#         availability_zone = "eu-west-1a"
#         size              = 500
#         type              = "gp2"
#       }
#     good: |
#       resource "aws_ebs_volume" "data" {
#         availability_zone = "eu-west-1a"
#         size              = 100
#         type              = "gp3"
#         throughput        = 250
#       }
#     fix: |
#       Change type to "gp3". The migration is in-place with no downtime. Where the gp2 volume was sized up to get IOPS rather than for capacity, size it back down and set iops and throughput explicitly.
package greensecops.iac_terraform.energy.gp2_volume_type

import rego.v1

violations contains violation if {
	some res in input.resource
	some name, volume in res.aws_ebs_volume
	volume.type == "gp2"

	violation := {
		"rule": "gp2_volume_type",
		"severity": "low",
		"category": "energy",
		"resource_address": sprintf("aws_ebs_volume.%v", [name]),
		"file_path": object.get(volume, "__tf_file", ""),
		"line_start": object.get(volume, "__start_line__", null),
		"line_end": object.get(volume, "__end_line__", null),
		"message": sprintf("Volume '%v' uses gp2. gp3 costs less per GB and decouples IOPS from capacity, so it removes the need to over-provision size to buy performance.", [name]),
	}
}

# root_block_device and ebs_block_device on an instance carry the same choice,
# and are where most gp2 volumes actually come from.
_block_devices(instance, key) := devices if {
	is_array(instance[key])
	devices := instance[key]
}

_block_devices(instance, key) := [instance[key]] if {
	is_object(instance[key])
}

violations contains violation if {
	some res in input.resource
	some name, instance in res.aws_instance
	some key in ["root_block_device", "ebs_block_device"]
	some device in _block_devices(instance, key)
	device.volume_type == "gp2"

	violation := {
		"rule": "gp2_volume_type",
		"severity": "low",
		"category": "energy",
		"resource_address": sprintf("aws_instance.%v", [name]),
		"file_path": object.get(instance, "__tf_file", ""),
		"line_start": object.get(instance, "__start_line__", null),
		"line_end": object.get(instance, "__end_line__", null),
		"message": sprintf("Instance '%v' declares a gp2 %v. gp3 costs less per GB and decouples IOPS from capacity.", [name, key]),
		"discriminator": key,
	}
}
