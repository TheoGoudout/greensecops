# METADATA
# title: Security group open to the world
# description: "An ingress rule allows traffic from 0.0.0.0/0 or ::/0, exposing the port to the entire internet rather than a scoped CIDR range. All three ways of writing one are covered: an inline ingress block on aws_security_group, the standalone aws_security_group_rule, and aws_vpc_security_group_ingress_rule, which is the form the AWS provider has recommended since v5 and which nothing here previously read. A rule opening exactly port 80 or exactly 443 is excluded — publishing HTTP and HTTPS is what a public service is."
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

_open_cidrs := {"0.0.0.0/0", "::/0"}

# Publishing 80 or 443 to the world is what a public service does. Only an
# exact single-port rule qualifies — a range that merely contains 443 is not
# "port 443 is published". `compose_port_bound_to_all_interfaces` made this
# distinction for Docker; this rule reported an ALB security group at critical.
_publicly_intended(from_port, to_port) if {
	from_port == to_port
	from_port in {80, 443}
}

_ports(from_port, _) := "every port" if not is_number(from_port)

_ports(from_port, to_port) := sprintf("%v", [from_port]) if {
	is_number(from_port)
	from_port == to_port
}

_ports(from_port, to_port) := sprintf("%v-%v", [from_port, to_port]) if {
	is_number(from_port)
	from_port != to_port
}

_as_list(value) := value if is_array(value)

_as_list(value) := [value] if is_object(value)

_finding(address, attrs, from_port, to_port, cidr) := {
	"rule": "open_ingress_security_group",
	"severity": "critical",
	"category": "security",
	"resource_address": address,
	"file_path": object.get(attrs, "__tf_file", ""),
	"line_start": object.get(attrs, "__start_line__", null),
	"line_end": object.get(attrs, "__end_line__", null),
	"message": sprintf("'%v' allows ingress from %v on %v.", [address, cidr, _ports(from_port, to_port)]),
	"context": sprintf("%v from %v", [_ports(from_port, to_port), cidr]),
	# A security group with several open rules produced several violations at
	# one resource address and no discriminator, so all but one were dropped on
	# the (resource_address, discriminator) dedup key and the survivor was
	# whichever one the set happened to keep.
	"discriminator": sprintf("%v:%v", [_ports(from_port, to_port), cidr]),
}

# ── Inline `ingress {}` blocks on aws_security_group ──────────────────────────
violations contains violation if {
	some res in input.resource
	some name, sg in res.aws_security_group
	some ingress in _as_list(sg.ingress)

	some field in ["cidr_blocks", "ipv6_cidr_blocks"]
	some cidr in ingress[field]
	cidr in _open_cidrs

	from_port := object.get(ingress, "from_port", null)
	to_port := object.get(ingress, "to_port", null)
	not _publicly_intended(from_port, to_port)

	violation := _finding(sprintf("aws_security_group.%v", [name]), sg, from_port, to_port, cidr)
}

# ── The standalone aws_security_group_rule ───────────────────────────────────
violations contains violation if {
	some res in input.resource
	some name, rule in res.aws_security_group_rule
	rule.type == "ingress"

	some field in ["cidr_blocks", "ipv6_cidr_blocks"]
	some cidr in rule[field]
	cidr in _open_cidrs

	from_port := object.get(rule, "from_port", null)
	to_port := object.get(rule, "to_port", null)
	not _publicly_intended(from_port, to_port)

	violation := _finding(sprintf("aws_security_group_rule.%v", [name]), rule, from_port, to_port, cidr)
}

# ── aws_vpc_security_group_ingress_rule: the provider-v5 form ────────────────
# One CIDR per resource rather than a list, under `cidr_ipv4`/`cidr_ipv6`. This
# is what the AWS provider has recommended since v5, and the rule did not read
# it at all — a root module written the current way was scanned and reported
# nothing.
violations contains violation if {
	some res in input.resource
	some name, rule in res.aws_vpc_security_group_ingress_rule

	some field in ["cidr_ipv4", "cidr_ipv6"]
	cidr := rule[field]
	cidr in _open_cidrs

	from_port := object.get(rule, "from_port", null)
	to_port := object.get(rule, "to_port", null)
	not _publicly_intended(from_port, to_port)

	violation := _finding(sprintf("aws_vpc_security_group_ingress_rule.%v", [name]), rule, from_port, to_port, cidr)
}
