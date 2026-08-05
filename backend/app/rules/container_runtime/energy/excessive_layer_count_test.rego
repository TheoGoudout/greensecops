package greensecops.container_runtime.energy.excessive_layer_count_test

import data.greensecops.container_runtime.energy.excessive_layer_count
import rego.v1

_layers(n) := [{"index": i, "size_bytes": 1000, "instruction": "RUN"} | some i in numbers.range(0, n - 1)]

_build(layers) := {"build": {"layers": layers}}

test_violation_above_the_threshold if {
	violations := excessive_layer_count.violations with input as _build(_layers(60))
	count(violations) == 1
	some v in violations
	contains(v.evidence, "60")
}

test_no_violation_at_the_threshold if {
	violations := excessive_layer_count.violations with input as _build(_layers(50))
	count(violations) == 0
}

test_no_violation_for_a_typical_image if {
	violations := excessive_layer_count.violations with input as _build(_layers(18))
	count(violations) == 0
}

test_no_violation_when_there_are_no_layers if {
	violations := excessive_layer_count.violations with input as _build([])
	count(violations) == 0
}

# The zero-config `docker history` collector can report no layer array at all;
# absent data is not a finding.
test_no_violation_when_layers_are_absent if {
	violations := excessive_layer_count.violations with input as {"build": {}}
	count(violations) == 0
}

test_no_violation_when_layers_is_null if {
	violations := excessive_layer_count.violations with input as _build(null)
	count(violations) == 0
}

test_one_finding_per_image_not_per_layer if {
	violations := excessive_layer_count.violations with input as _build(_layers(200))
	count(violations) == 1
}
