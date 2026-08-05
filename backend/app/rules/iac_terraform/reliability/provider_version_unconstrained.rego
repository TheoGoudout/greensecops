# METADATA
# title: Provider declared without a version constraint
# description: A required_providers entry names a source but no version, so Terraform resolves the newest release at init time. The configuration then means different things on different days — a provider major version can rename attributes, change defaults, or start planning a replacement where it previously planned an update, which turns an unrelated apply into a destroy. It is the same class of problem as unpinned_actions and unpinned_base_image, on the layer that manages everything else.
# custom:
#   severity: medium
#   detection: static_analysis
#   examples:
#     bad: |
#       terraform {
#         required_providers {
#           aws = {
#             source = "hashicorp/aws"
#           }
#         }
#       }
#     good: |
#       terraform {
#         required_providers {
#           aws = {
#             source  = "hashicorp/aws"
#             version = "~> 6.0"
#           }
#         }
#       }
#     fix: |
#       Add a version constraint — "~> 6.0" allows patch and minor updates while holding the major version. Commit .terraform.lock.hcl alongside it so every run resolves to the same provider build, not merely to a compatible one.
package greensecops.iac_terraform.reliability.provider_version_unconstrained

import rego.v1

# A nested HCL block arrives as a single-element list; the same block in a
# .tf.json file is a bare object.
_required_providers(block) := entries if {
	is_array(block.required_providers)
	entries := block.required_providers
}

_required_providers(block) := [block.required_providers] if {
	is_object(block.required_providers)
}

violations contains violation if {
	some block in input.terraform
	some entry in _required_providers(block)
	some provider_name, spec in entry

	# The parser stamps its source-span keys into the same mapping the provider
	# names live in, so they have to be skipped or `__start_line__` is reported
	# as an unconstrained provider.
	not startswith(provider_name, "__")

	# A provider may also be written as a bare source string rather than an
	# object, which likewise carries no version.
	not _has_version(spec)

	violation := {
		"rule": "provider_version_unconstrained",
		"severity": "medium",
		"category": "reliability",
		"resource_address": sprintf("required_providers.%v", [provider_name]),
		"file_path": object.get(block, "__tf_file", ""),
		"line_start": object.get(block, "__start_line__", null),
		"line_end": object.get(block, "__end_line__", null),
		"message": sprintf("Provider '%v' has no version constraint, so terraform init resolves whatever is newest and the configuration means something different on a later run.", [provider_name]),
		"discriminator": provider_name,
	}
}

_has_version(spec) if {
	is_object(spec)
	spec.version
}
