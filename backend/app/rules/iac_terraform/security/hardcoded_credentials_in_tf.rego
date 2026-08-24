# METADATA
# title: Hardcoded credential in Terraform
# description: "A literal credential is written into the configuration rather than passed as a variable or read from a secrets manager. Terraform source is committed, so the value is readable by anyone who can read the repository, is copied into every clone, and survives in git history after the line is deleted — it has to be rotated, not just removed. Every block type is scanned, not only resources: a provider block with a literal access key is the most common form of this by a wide margin, and it is not a resource."
# custom:
#   severity: critical
#   severity_weight: 4.0
#   detection: pattern_matching
#   examples:
#     bad: |
#       provider "aws" {
#         region     = "eu-west-1"
#         access_key = "AKIAIOSFODNN7EXAMPLE"
#         secret_key = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
#       }
#     good: |
#       provider "aws" {
#         region = "eu-west-1"
#       }
#     fix: |
#       Remove the literal, let the provider read credentials from the environment or an assumed role, and rotate the exposed key — a credential that has been committed is compromised from the push that added it, and deleting the line does not remove it from history.
package greensecops.iac_terraform.security.hardcoded_credentials_in_tf

import data.greensecops.lib.secrets
import rego.v1

# This used to walk `input.resource` only, matching a single pattern (`AKIA`).
# Two gaps followed from that. A `provider "aws"` block with `access_key =
# "AKIA..."` — the textbook version of this mistake, and the one that appears
# in every "getting started" blog post — is not under `input.resource`, so it
# was never scanned. And `lib/secrets.known_credential` already recognised nine
# credential formats for the workflow engine while this rule recognised one.

# `resource` and `data` nest one level deeper than every other block type —
# {type: {name: attrs}} against {name: attrs} — which is the same distinction
# `hcl_parser._TWO_LEVEL_BLOCK_TYPES` makes when it stamps `__tf_file`. Two
# clauses rather than one so the reported address is the real one
# (`aws_instance.app`, `provider.aws`) instead of the block keyword.
_two_level := {"resource", "data"}

_one_level := {"provider", "locals", "variable", "output", "module"}

_holds_a_credential(subtree) if {
	walk(subtree, [_, value])
	is_string(value)
	secrets.known_credential(value)
}

_finding(address, attrs, context) := {
	"rule": "hardcoded_credentials_in_tf",
	"severity": "critical",
	"category": "security",
	"resource_address": address,
	"file_path": object.get(attrs, "__tf_file", ""),
	"line_start": object.get(attrs, "__start_line__", null),
	"line_end": object.get(attrs, "__end_line__", null),
	"message": sprintf("'%v' contains a literal matching a known credential format. Move it out of the configuration and rotate it — it is in git history from the commit that added it.", [address]),
	"context": context,
	# Never the credential itself: that would put the secret into the issue's
	# fingerprint and its identity. The block is enough — a block with two
	# leaked keys has one problem.
	"discriminator": address,
}

violations contains violation if {
	some block_type in _two_level
	some block in input[block_type]
	some res_type, named in block
	some name, attrs in named
	is_object(attrs)
	_holds_a_credential(attrs)

	violation := _finding(sprintf("%v.%v", [res_type, name]), attrs, block_type)
}

violations contains violation if {
	some block_type in _one_level
	some block in input[block_type]
	some name, attrs in block
	is_object(attrs)
	not startswith(name, "__")
	_holds_a_credential(attrs)

	violation := _finding(sprintf("%v.%v", [block_type, name]), attrs, block_type)
}
