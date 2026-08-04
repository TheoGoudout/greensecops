package greensecops.ci_telemetry.reliability.runner_disk_pressure_test

import data.greensecops.ci_telemetry.reliability.runner_disk_pressure
import rego.v1

# disk_free_gb is optional on RunnerSpecs -- the Action omits it when `df`
# could not be parsed, and an unmeasured disk is not a full one.

_specs(specs) := {"runner_specs": specs, "metrics": {}}

test_violation_below_the_threshold if {
	violations := runner_disk_pressure.violations with input as _specs({"vcpus": 4, "disk_free_gb": 1.2})
	count(violations) == 1
	some v in violations
	v.evidence == "disk_free_gb=1.2"
}

test_no_violation_at_the_threshold if {
	violations := runner_disk_pressure.violations with input as _specs({"vcpus": 4, "disk_free_gb": 2.0})
	count(violations) == 0
}

test_no_violation_with_plenty_of_disk if {
	violations := runner_disk_pressure.violations with input as _specs({"vcpus": 4, "disk_free_gb": 50})
	count(violations) == 0
}

test_no_violation_when_disk_was_not_measured if {
	violations := runner_disk_pressure.violations with input as _specs({"vcpus": 4})
	count(violations) == 0
}

# A whole-number reading is an integer after the round-trip, which sprintf's
# %f rejected before the formatting fix.
test_evidence_is_readable_for_a_whole_number_of_gigabytes if {
	violations := runner_disk_pressure.violations with input as _specs({"vcpus": 4, "disk_free_gb": 1})
	some v in violations
	v.evidence == "disk_free_gb=1"
}
