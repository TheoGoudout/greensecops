# METADATA
# title: Root module declares no remote state backend
# description: The configuration has a terraform block but no backend or cloud block, so state is written to a local terraform.tfstate file. That file is the only record of what Terraform believes exists, it holds every attribute of every resource including ones marked sensitive, and it has no locking — so two people applying at once corrupt it, and losing the machine it lives on means losing the ability to manage the infrastructure it describes at all.
# custom:
#   severity: high
#   detection: static_analysis
#   examples:
#     bad: |
#       terraform {
#         required_version = ">= 1.9"
#       }
#     good: |
#       terraform {
#         required_version = ">= 1.9"
#
#         backend "s3" {
#           bucket       = "tfstate"
#           key          = "prod/terraform.tfstate"
#           region       = "eu-west-1"
#           use_lockfile = true
#         }
#       }
#     fix: |
#       Add a backend block — S3 with use_lockfile, or the equivalent for your provider — or a cloud block for HCP Terraform. Whichever you pick, make sure the state store is versioned and encrypted, because it holds resource attributes that are secrets.
package greensecops.iac_terraform.reliability.missing_remote_backend

import rego.v1

# `terraform` blocks are a top-level list like every other block type, and a
# root module can have more than one (Terraform merges them). Any one of them
# declaring a backend settles it for the module.
_declares_remote_state if {
	some block in input.terraform
	some key in ["backend", "cloud"]
	block[key]
}

# Only a *root* module has state to store — a child module cannot declare a
# backend at all, and pinning its providers in a `terraform` block is
# idiomatic, so firing on that would report almost every shared module.
# Configuring a provider is what separates the two: HashiCorp's guidance is
# that a shared module inherits its providers rather than declaring them, and
# this repository's own deploy/terraform follows it — the roots have
# `provider` blocks and modules/ has none.
_is_root_module if {
	count(object.get(input, "provider", [])) > 0
}

# Fires once per module, not once per terraform block. The finding is about
# the configuration as a whole, so it reports against the first block that
# gives it a file and a line to point at.
_first_terraform_block := block if {
	some block in input.terraform
	block.__start_line__ == min({line |
		some candidate in input.terraform
		line := candidate.__start_line__
	})
}

violations contains violation if {
	count(object.get(input, "terraform", [])) > 0
	_is_root_module
	not _declares_remote_state

	block := _first_terraform_block
	violation := {
		"rule": "missing_remote_backend",
		"severity": "high",
		"category": "reliability",
		"resource_address": "terraform",
		"file_path": object.get(block, "__tf_file", ""),
		"line_start": object.get(block, "__start_line__", null),
		"line_end": object.get(block, "__end_line__", null),
		"message": "The root module declares no backend or cloud block, so state is kept in a local file with no locking and no backup — and that file holds every resource attribute, including the sensitive ones.",
	}
}
