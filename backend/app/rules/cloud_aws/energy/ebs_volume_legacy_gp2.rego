# METADATA
# title: EBS volume still uses the gp2 type
# description: An EBS volume is on gp2, the previous-generation general-purpose SSD. gp3 gives the same durability and better baseline performance for around 20 percent less, and decouples IOPS from volume size — which is the real waste in gp2, where the only way to get more throughput is to provision storage you do not need and will never fill. The migration is an online modification with no snapshot, no detach and no downtime, which makes this one of the few findings here that is purely a saving with no trade.
# custom:
#   severity: low
#   detection: cloud_posture
#   examples:
#     bad: |
#       aws ec2 create-volume --size 500 --volume-type gp2 \
#         --availability-zone eu-west-1a
#     good: |
#       aws ec2 create-volume --size 100 --volume-type gp3 --iops 6000 \
#         --availability-zone eu-west-1a
#     fix: |
#       Run `aws ec2 modify-volume --volume-id <id> --volume-type gp3`. It applies to a live, attached volume. If the volume was oversized purely to buy IOPS, shrink the provisioned IOPS decision back to what the workload needs once the type change settles.
package greensecops.cloud_aws.energy.ebs_volume_legacy_gp2

import rego.v1

violations contains violation if {
	some volume in input.ebs_volumes

	volume.volume_type == "gp2"

	violation := {
		"rule": "ebs_volume_legacy_gp2",
		"severity": "low",
		"category": "energy",
		"resource_type": "aws_ebs_volume",
		"resource_id": volume.id,
		"region": volume.region,
		"message": sprintf("Volume '%v' (%v GB) is gp2. gp3 is cheaper for the same durability and can be switched online with no downtime.", [volume.id, object.get(volume, "size_gb", 0)]),
	}
}
