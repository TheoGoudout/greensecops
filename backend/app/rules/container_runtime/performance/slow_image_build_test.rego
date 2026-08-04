package greensecops.container_runtime.performance.slow_image_build_test

import data.greensecops.container_runtime.performance.slow_image_build
import rego.v1

_build(duration) := {"build": {"build_duration_ms": duration}}

test_violation_on_a_long_build if {
	violations := slow_image_build.violations with input as _build(900000)
	count(violations) == 1
	some v in violations
	v.category == "performance"
	contains(v.evidence, "15 minutes")
}

test_no_violation_at_the_threshold if {
	violations := slow_image_build.violations with input as _build(300000)
	count(violations) == 0
}

test_no_violation_on_a_fast_build if {
	violations := slow_image_build.violations with input as _build(95000)
	count(violations) == 0
}

# build_duration_ms is optional on the ingest payload; an unmeasured build is
# not a slow one.
test_no_violation_when_duration_is_null if {
	violations := slow_image_build.violations with input as _build(null)
	count(violations) == 0
}

test_no_violation_when_duration_is_absent if {
	violations := slow_image_build.violations with input as {"build": {}}
	count(violations) == 0
}
