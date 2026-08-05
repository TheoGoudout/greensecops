# METADATA
# title: Security group allows all outbound traffic
# description: A security group permits egress to every address on every port. AWS applies this to the default group and to any group created without an explicit egress rule, so it is almost never a decision anybody made. It matters because egress is what turns a foothold into an incident — it is the path a compromised instance uses to reach a command-and-control host, fetch a second stage, or copy a database out. Ingress controls decide whether an attacker gets in; egress controls decide what it costs you when they do.
# custom:
#   severity: medium
#   detection: cloud_posture
#   examples:
#     bad: |
#       aws ec2 authorize-security-group-egress --group-id sg-0123 \
#         --protocol -1 --cidr 0.0.0.0/0
#     good: |
#       aws ec2 authorize-security-group-egress --group-id sg-0123 \
#         --protocol tcp --port 443 --cidr 10.0.0.0/16
#     fix: |
#       Revoke the catch-all rule and add the destinations the workload actually needs — your VPC range, a NAT range, or the prefix list of the AWS service it calls. Where a host genuinely needs the internet, route it through a proxy you can log rather than opening the group.
package greensecops.cloud_aws.security.security_group_unrestricted_egress

import rego.v1

# `-1` is how the API spells "every protocol"; a rule naming a single protocol
# with no port range is the same thing scoped to that protocol.
_all_protocols(egress) if egress.ip_protocol == "-1"

violations contains violation if {
	some sg in input.security_groups
	some index, egress in sg.egress_rules

	_all_protocols(egress)
	some cidr in egress.cidr_blocks
	cidr in {"0.0.0.0/0", "::/0"}

	violation := {
		"rule": "security_group_unrestricted_egress",
		"severity": "medium",
		"category": "security",
		"resource_type": "aws_security_group",
		"resource_id": sg.id,
		"region": sg.region,
		"message": sprintf("Security group '%v' (%v) allows all outbound traffic to %v, so a compromised instance using it can reach anything on the internet.", [sg.name, sg.id, cidr]),
		"discriminator": sprintf("egress-%v-%v", [index, cidr]),
	}
}
