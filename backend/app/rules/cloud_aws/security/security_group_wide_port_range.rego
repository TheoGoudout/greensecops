# METADATA
# title: Security group opens a wide range of ports
# description: A live security group has an ingress rule spanning a large port range, or allowing all protocols. This is independent of where the traffic comes from — open_ingress_security_group covers the rules reachable from the internet, while this one fires even on a private CIDR, because a range that wide grants far more than the service behind it needs. Ranges like this are usually written once during debugging and never narrowed.
# custom:
#   severity: medium
#   detection: cloud_posture
#   examples:
#     bad: |
#       aws ec2 authorize-security-group-ingress --group-id sg-0123 \
#         --protocol tcp --port 0-65535 --cidr 10.0.0.0/16
#     good: |
#       aws ec2 authorize-security-group-ingress --group-id sg-0123 \
#         --protocol tcp --port 5432 --cidr 10.0.0.0/16
#     fix: |
#       Replace the range with the ports the service actually listens on, one rule per port. If the range exists because the port is assigned dynamically, prefer a fixed port or a service discovery mechanism over leaving the range open.
package greensecops.cloud_aws.security.security_group_wide_port_range

import rego.v1

# Wider than a service and its handful of neighbours. Deliberately generous:
# the point is to catch 0-65535 and its near relatives, not to argue about a
# legitimate span of a few dozen ports.
_wide_range_size := 100

_range_size(ingress) := to_port - from_port if {
	from_port := ingress.from_port
	to_port := ingress.to_port
	is_number(from_port)
	is_number(to_port)
}

violations contains violation if {
	some sg in input.security_groups
	some ingress in sg.ingress_rules
	span := _range_size(ingress)
	span >= _wide_range_size

	violation := {
		"rule": "security_group_wide_port_range",
		"severity": "medium",
		"category": "security",
		"resource_type": "aws_security_group",
		"resource_id": sg.id,
		"region": sg.region,
		"message": sprintf("Security group '%v' (%v) allows ingress across ports %v-%v.", [sg.name, sg.id, ingress.from_port, ingress.to_port]),
		"discriminator": sprintf("%v-%v", [ingress.from_port, ingress.to_port]),
	}
}

# `-1` is how EC2 reports "every protocol", and such a rule carries no port
# range at all — there is nothing to measure a span against, but it grants
# strictly more than any range would.
violations contains violation if {
	some sg in input.security_groups
	some ingress in sg.ingress_rules
	ingress.ip_protocol == "-1"

	violation := {
		"rule": "security_group_wide_port_range",
		"severity": "medium",
		"category": "security",
		"resource_type": "aws_security_group",
		"resource_id": sg.id,
		"region": sg.region,
		"message": sprintf("Security group '%v' (%v) allows ingress on every protocol and port.", [sg.name, sg.id]),
		"discriminator": "all-protocols",
	}
}
