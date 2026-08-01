package greensecops.container_runtime.energy.image_layer_cache_ineffective_test

import data.greensecops.container_runtime.energy.image_layer_cache_ineffective
import rego.v1

test_violation_when_ratio_is_low_across_several_builds if {
	violations := image_layer_cache_ineffective.violations with input as {"build": {
		"cache_hit_ratio": 0.18,
		"observed_builds": 6,
	}}
	count(violations) == 1
}

test_no_violation_when_the_cache_is_working if {
	violations := image_layer_cache_ineffective.violations with input as {"build": {
		"cache_hit_ratio": 0.86,
		"observed_builds": 6,
	}}
	count(violations) == 0
}

# The first build of any image misses every layer legitimately, so a low ratio
# means nothing until the build has repeated.
test_no_violation_before_enough_builds_observed if {
	violations := image_layer_cache_ineffective.violations with input as {"build": {
		"cache_hit_ratio": 0.0,
		"observed_builds": 1,
	}}
	count(violations) == 0
}

test_no_violation_without_telemetry if {
	violations := image_layer_cache_ineffective.violations with input as {"build": {}}
	count(violations) == 0
}
