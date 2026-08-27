package greensecops.iac_terraform.reliability.missing_remote_backend_test

import data.greensecops.iac_terraform.reliability.missing_remote_backend
import rego.v1

# `terraform` is the one unnamed block type — its entry *is* the attrs dict.
# hcl_parser stamps __tf_file onto it directly for exactly this reason.

# Only a root module is judged, and declaring a provider is what marks one —
# so every case here carries a provider block unless it is testing that.
_terraform(blocks) := {
	"terraform": blocks,
	"provider": [{"aws": {"region": "eu-west-1"}}],
}

_block(attrs, line) := _block_in_file(attrs, line, "versions.tf")

_block_in_file(attrs, line, file) := object.union(
	{"__tf_file": file, "__start_line__": line, "__end_line__": line + 6},
	attrs,
)

test_violation_when_no_backend_is_declared if {
	violations := missing_remote_backend.violations with input as _terraform([_block({"required_version": ">= 1.9"}, 1)])
	count(violations) == 1
	some v in violations
	v.resource_address == "terraform"
	v.file_path == "versions.tf"
	v.line_start == 1
}

test_no_violation_with_an_s3_backend if {
	violations := missing_remote_backend.violations with input as _terraform([_block(
		{"backend": [{"s3": {"bucket": "tfstate", "key": "prod/terraform.tfstate"}}]},
		1,
	)])
	count(violations) == 0
}

test_no_violation_with_a_cloud_block if {
	violations := missing_remote_backend.violations with input as _terraform([_block(
		{"cloud": [{"organization": "acme"}]},
		1,
	)])
	count(violations) == 0
}

# Terraform merges multiple terraform blocks, so a backend in any one of them
# settles it for the module.
test_no_violation_when_a_second_block_declares_the_backend if {
	violations := missing_remote_backend.violations with input as _terraform([
		_block({"required_version": ">= 1.9"}, 1),
		_block({"backend": [{"s3": {"bucket": "tfstate"}}]}, 20),
	])
	count(violations) == 0
}

# One finding for the module, reported against the earliest block so the line
# is stable however the blocks are ordered in the merged document.
test_one_finding_per_module_reported_at_the_first_block if {
	violations := missing_remote_backend.violations with input as _terraform([
		_block({"required_version": ">= 1.9"}, 20),
		_block({"required_providers": [{"aws": {"source": "hashicorp/aws"}}]}, 1),
	])
	count(violations) == 1
	some v in violations
	v.line_start == 1
}

# A module with no terraform block at all is a child module, which inherits the
# root's backend and must not be reported.
test_no_violation_when_there_is_no_terraform_block if {
	violations := missing_remote_backend.violations with input as {"resource": []}
	count(violations) == 0
}

# A shared module pins its providers in a terraform block but cannot declare a
# backend — only a root module can. Declaring no provider is what marks it as
# a child, and firing here would report almost every module in existence.
test_no_violation_for_a_child_module_pinning_providers if {
	violations := missing_remote_backend.violations with input as {"terraform": [{
		"required_providers": [{"aws": {"source": "hashicorp/aws", "version": "~> 6.0"}}],
		"__tf_file": "versions.tf",
		"__start_line__": 1,
		"__end_line__": 7,
	}]}
	count(violations) == 0
}

test_no_violation_for_an_empty_terraform_list if {
	violations := missing_remote_backend.violations with input as _terraform([])
	count(violations) == 0
}

# __start_line__ is per-file, so two blocks from different files routinely
# share it (most .tf files open their terraform block at line 1). Before the
# tie-break included __tf_file, this made _first_terraform_block a complete
# rule with two valid outputs — an eval_conflict_error (500) at query time,
# not a wrong answer. Asserting a single, deterministic winner is the
# regression coverage for that production incident.
test_one_finding_when_two_blocks_tie_on_start_line_across_files if {
	violations := missing_remote_backend.violations with input as _terraform([
		_block_in_file({"required_version": ">= 1.9"}, 1, "main.tf"),
		_block_in_file({"required_providers": [{"aws": {"source": "hashicorp/aws"}}]}, 1, "versions.tf"),
	])
	count(violations) == 1
	some v in violations
	v.file_path == "main.tf"
	v.line_start == 1
}
