# METADATA
# title: Live security group open to the world
# description: "A live EC2 security group has an ingress rule allowing traffic from 0.0.0.0/0 or ::/0, exposing the port to the entire internet rather than a scoped CIDR range. A rule that opens exactly port 80 or exactly port 443 is excluded: publishing HTTP and HTTPS to the world is what a public service is, and reporting it at critical buried the rules that matter — SSH, RDP, a database port, or a range wide enough to contain one."
# custom:
#   severity: critical
#   detection: cloud_posture
#   examples:
#     bad: |
#       aws ec2 authorize-security-group-ingress --group-id sg-0123 \
#         --protocol tcp --port 22 --cidr 0.0.0.0/0
#     good: |
#       aws ec2 authorize-security-group-ingress --group-id sg-0123 \
#         --protocol tcp --port 22 --cidr 10.0.0.0/16
#     fix: |
#       Scope the ingress rule's CIDR to a known range, or front the service with a load balancer/VPN and revoke the direct public rule.
package greensecops.cloud_aws.security.open_ingress_security_group

import rego.v1

# `compose_port_bound_to_all_interfaces` already made this distinction for
# Docker — it reports a database published on every interface and says nothing
# about a web port — and this rule did not. A load balancer security group open
# on 443 is not a finding, and reporting it at critical alongside an SSH rule
# taught readers to skim the list.
#
# Only an exact single-port rule qualifies: `0-65535` contains 443 and is not
# "port 443 is published".
_publicly_intended(ingress) if {
	_from(ingress) == _to(ingress)
	_from(ingress) in {80, 443}
}

# An `-1` protocol rule carries no port range at all, and the collector passes
# the absence straight through as null.
_from(ingress) := object.get(ingress, "from_port", null)

_to(ingress) := object.get(ingress, "to_port", null)

_port_label(ingress) := "every port" if not is_number(_from(ingress))

_port_label(ingress) := sprintf("%v", [_from(ingress)]) if {
	is_number(_from(ingress))
	_from(ingress) == _to(ingress)
}

_port_label(ingress) := sprintf("%v-%v", [_from(ingress), _to(ingress)]) if {
	is_number(_from(ingress))
	_from(ingress) != _to(ingress)
}

violations contains violation if {
	some sg in input.security_groups
	some index, ingress in sg.ingress_rules
	some cidr in ingress.cidr_blocks
	cidr in {"0.0.0.0/0", "::/0"}
	not _publicly_intended(ingress)

	ports := _port_label(ingress)
	violation := {
		"rule": "open_ingress_security_group",
		"severity": "critical",
		"category": "security",
		"resource_type": "aws_security_group",
		"resource_id": sg.id,
		"region": sg.region,
		"message": sprintf("Security group '%v' (%v) allows ingress from %v on %v.", [sg.name, sg.id, cidr, ports]),
		"context": sprintf("%v %v from %v", [object.get(ingress, "ip_protocol", "any"), ports, cidr]),
		# Without this, a group open on 22, 443 and 5432 produced three
		# violations that collapsed to one issue on (resource_id, discriminator)
		# — and which port the surviving row named was arbitrary.
		"discriminator": sprintf("%v:%v:%v", [index, ports, cidr]),
	}
}
