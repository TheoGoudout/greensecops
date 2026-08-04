package greensecops.ci_telemetry.performance.runner_cpu_saturated_test

import data.greensecops.ci_telemetry.performance.runner_cpu_saturated
import rego.v1

_run(vcpus, cpu) := {"runner_specs": {"vcpus": vcpus}, "metrics": {"cpu_load_percent": cpu}}

test_violation_when_a_small_runner_is_pinned if {
	violations := runner_cpu_saturated.violations with input as _run(2, 98.0)
	count(violations) == 1
	some v in violations
	v.category == "performance"
	contains(v.evidence, "2-vCPU")
}

test_violation_exactly_at_the_saturation_threshold if {
	violations := runner_cpu_saturated.violations with input as _run(2, 95.0)
	count(violations) == 1
}

test_no_violation_below_the_saturation_threshold if {
	violations := runner_cpu_saturated.violations with input as _run(4, 68.0)
	count(violations) == 0
}

# A large runner at full tilt is doing what it was sized for; runner_sizing and
# runner_underutilized are the rules that look at large runners.
test_no_violation_on_a_large_runner if {
	violations := runner_cpu_saturated.violations with input as _run(8, 99.0)
	count(violations) == 0
}

test_no_violation_when_cpu_was_not_measured if {
	violations := runner_cpu_saturated.violations with input as {"runner_specs": {"vcpus": 2}, "metrics": {}}
	count(violations) == 0
}

test_no_violation_when_cpu_is_null if {
	violations := runner_cpu_saturated.violations with input as _run(2, null)
	count(violations) == 0
}

# This rule and runner_underutilized are complementary and can never both fire:
# one needs CPU at or above 95%, the other below 25%.
test_does_not_overlap_with_runner_underutilized if {
	violations := runner_cpu_saturated.violations with input as _run(2, 12.0)
	count(violations) == 0
}

test_evidence_is_readable_for_a_whole_number_percentage if {
	violations := runner_cpu_saturated.violations with input as _run(2, 100)
	some v in violations
	v.evidence == "CPU was at 100% on a 2-vCPU runner"
}
