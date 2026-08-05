package greensecops.iac_terraform.reliability.provider_version_unconstrained_test

import data.greensecops.iac_terraform.reliability.provider_version_unconstrained as unconstrained
import rego.v1

# hcl_parser stamps __start_line__/__end_line__ into the *same* mapping the
# provider names live in, so the rule has to skip them — otherwise
# `__start_line__` is reported as a provider with no version.

_terraform(required_providers) := {"terraform": [{
	"required_providers": [object.union(
		{"__start_line__": 4, "__end_line__": 7},
		required_providers,
	)],
	"__tf_file": "versions.tf",
	"__start_line__": 2,
	"__end_line__": 8,
}]}

test_violation_for_a_provider_without_a_version if {
	violations := unconstrained.violations with input as _terraform({"random": {"source": "hashicorp/random"}})
	count(violations) == 1
	some v in violations
	v.resource_address == "required_providers.random"
	v.file_path == "versions.tf"
}

test_no_violation_when_a_version_is_pinned if {
	violations := unconstrained.violations with input as _terraform({"aws": {
		"source": "hashicorp/aws",
		"version": "~> 6.0",
	}})
	count(violations) == 0
}

# The source-span keys share the mapping with the provider names; reporting
# __start_line__ as an unconstrained provider is the bug this pins.
test_does_not_report_the_parser_source_span_keys if {
	violations := unconstrained.violations with input as _terraform({"aws": {
		"source": "hashicorp/aws",
		"version": "~> 6.0",
	}})
	count(violations) == 0
}

test_reports_only_the_unconstrained_providers if {
	violations := unconstrained.violations with input as _terraform({
		"aws": {"source": "hashicorp/aws", "version": "~> 6.0"},
		"random": {"source": "hashicorp/random"},
		"null": {"source": "hashicorp/null"},
	})
	count(violations) == 2
	{v.discriminator | some v in violations} == {"random", "null"}
}

# A provider written as a bare source string carries no version either.
test_violation_for_a_bare_source_string if {
	violations := unconstrained.violations with input as _terraform({"random": "hashicorp/random"})
	count(violations) == 1
}

test_no_violation_when_there_are_no_required_providers if {
	violations := unconstrained.violations with input as {"terraform": [{
		"required_version": ">= 1.9",
		"__tf_file": "versions.tf",
		"__start_line__": 2,
		"__end_line__": 4,
	}]}
	count(violations) == 0
}

# .tf.json carries the block as a bare object rather than a single-element list.
test_violation_for_the_json_style_object_form if {
	violations := unconstrained.violations with input as {"terraform": [{
		"required_providers": {"random": {"source": "hashicorp/random"}},
		"__tf_file": "versions.tf.json",
		"__start_line__": 2,
		"__end_line__": 8,
	}]}
	count(violations) == 1
}
