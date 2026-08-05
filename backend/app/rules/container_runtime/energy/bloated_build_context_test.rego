package greensecops.container_runtime.energy.bloated_build_context_test

import data.greensecops.container_runtime.energy.bloated_build_context
import rego.v1

test_violation_when_context_dwarfs_the_image if {
	violations := bloated_build_context.violations with input as {"build": {
		"context_size_bytes": 900000000,
		"image_size_bytes": 90000000,
	}}
	count(violations) == 1
}

test_no_violation_when_context_is_proportionate if {
	violations := bloated_build_context.violations with input as {"build": {
		"context_size_bytes": 12000000,
		"image_size_bytes": 90000000,
	}}
	count(violations) == 0
}

# A small project can exceed the ratio harmlessly; the absolute floor keeps
# this to contexts whose transfer actually costs something.
test_no_violation_for_a_small_context_with_a_high_ratio if {
	violations := bloated_build_context.violations with input as {"build": {
		"context_size_bytes": 9000000,
		"image_size_bytes": 1000000,
	}}
	count(violations) == 0
}

# Regression for the sprintf %f/integer bug: a ratio or size that divides
# evenly became an integer, which %f renders as "%!f(int=N)" in the finding
# the user reads.
test_evidence_is_readable_when_the_numbers_divide_evenly if {
	violations := bloated_build_context.violations with input as {"build": {
		"context_size_bytes": 400000000,
		"image_size_bytes": 100000000,
	}}
	some v in violations
	v.evidence == "context 400 MB vs image 100 MB (4x)"
}
