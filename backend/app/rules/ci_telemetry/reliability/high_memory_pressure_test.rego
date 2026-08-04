package greensecops.ci_telemetry.reliability.high_memory_pressure_test

import data.greensecops.ci_telemetry.reliability.high_memory_pressure
import rego.v1

# Input is the {"runner_specs", "metrics"} pair the TelemetryRun row stores.
# Every metrics field is optional, so absence has to be quiet.

_metrics(metrics) := {"runner_specs": {"vcpus": 4}, "metrics": metrics}

test_violation_above_the_threshold if {
	violations := high_memory_pressure.violations with input as _metrics({"ram_percent": 93.5})
	count(violations) == 1
	some v in violations
	v.severity == "high"
}

test_no_violation_at_the_threshold if {
	violations := high_memory_pressure.violations with input as _metrics({"ram_percent": 90.0})
	count(violations) == 0
}

test_no_violation_for_normal_usage if {
	violations := high_memory_pressure.violations with input as _metrics({"ram_percent": 48.0})
	count(violations) == 0
}

test_no_violation_when_ram_was_not_measured if {
	violations := high_memory_pressure.violations with input as _metrics({"cpu_load_percent": 40.0})
	count(violations) == 0
}

# The Action rounds to one decimal, so a whole-number reading arrives as an
# integer -- which sprintf's %f rejected before the formatting fix.
test_evidence_is_readable_for_a_whole_number_percentage if {
	violations := high_memory_pressure.violations with input as _metrics({"ram_percent": 95})
	some v in violations
	v.evidence == "RAM=95%"
}

test_one_finding_per_run if {
	violations := high_memory_pressure.violations with input as _metrics({"ram_percent": 99.0, "cpu_load_percent": 80.0})
	count(violations) == 1
}
