# METADATA
# title: Security group open to the world
# description: An aws_security_group ingress rule allows traffic from 0.0.0.0/0, exposing the port to the entire internet rather than a scoped CIDR range.
# custom:
#   severity: critical
#   detection: static_analysis
#   examples:
#     bad: |
#       resource "aws_security_group" "web" {
#         ingress {
#           from_port   = 22
#           to_port     = 22
#           cidr_blocks = ["0.0.0.0/0"]
#         }
#       }
#     good: |
#       resource "aws_security_group" "web" {
#         ingress {
#           from_port   = 22
#           to_port     = 22
#           cidr_blocks = ["10.0.0.0/16"]
#         }
#       }
#     fix: |
#       Scope cidr_blocks to a known range (VPN, bastion, office IP), or front the service with a load balancer / VPN and remove the direct public ingress rule.
package greensecops.iac_terraform.security.open_ingress_security_group

import rego.v1

violations contains violation if {
	some res in input.resource
	some name, sg in res.aws_security_group
	some ingress in sg.ingress
	some cidr in ingress.cidr_blocks
	cidr == "0.0.0.0/0"
	violation := {
		"rule": "open_ingress_security_group",
		"severity": "critical",
		"category": "security",
		"resource_address": sprintf("aws_security_group.%v", [name]),
		"file_path": object.get(sg, "__tf_file", ""),
		"line_start": object.get(sg, "__start_line__", null),
		"line_end": object.get(sg, "__end_line__", null),
		"message": sprintf(
			"Security group '%v' allows ingress from 0.0.0.0/0 on port %v.",
			[name, object.get(ingress, "from_port", "?")],
		),
	}
}
