# METADATA
# title: Live security group open to the world
# description: A live EC2 security group has an ingress rule allowing traffic from 0.0.0.0/0 or ::/0, exposing the port to the entire internet rather than a scoped CIDR range.
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

violations contains violation if {
	some sg in input.security_groups
	some ingress in sg.ingress_rules
	some cidr in ingress.cidr_blocks
	cidr in {"0.0.0.0/0", "::/0"}
	violation := {
		"rule": "open_ingress_security_group",
		"severity": "critical",
		"category": "security",
		"resource_type": "aws_security_group",
		"resource_id": sg.id,
		"region": sg.region,
		"message": sprintf("Security group '%v' (%v) allows ingress from %v on port %v.", [sg.name, sg.id, cidr, object.get(ingress, "from_port", "?")]),
	}
}
