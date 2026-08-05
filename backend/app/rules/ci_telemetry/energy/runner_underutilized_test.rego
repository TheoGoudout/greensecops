package greensecops.ci_telemetry.energy.runner_underutilized_test

import data.greensecops.ci_telemetry.energy.runner_underutilized
import rego.v1

# All three conditions have to hold: a large runner, low CPU *and* low RAM.
# The defaults are deliberately pessimistic (100% for an unmeasured metric) so
# a run with no telemetry never reads as underutilized.

_run(vcpus, cpu, ram) := {
	"runner_specs": {"vcpus": vcpus},
	"metrics": {"cpu_load_percent": cpu, "ram_percent": ram},
}

test_violation_on_a_large_idle_runner if {
	violations := runner_underutilized.violations with input as _run(8, 12.0, 18.0)
	count(violations) == 1
	some v in violations
	v.category == "energy"
	contains(v.evidence, "vCPUs=8")
}

test_no_violation_on_a_busy_large_runner if {
	violations := runner_underutilized.violations with input as _run(8, 71.0, 64.0)
	count(violations) == 0
}

# Low CPU with high RAM is a memory-bound job using what it was given.
test_no_violation_when_only_cpu_is_low if {
	violations := runner_underutilized.violations with input as _run(8, 12.0, 80.0)
	count(violations) == 0
}

test_no_violation_when_only_ram_is_low if {
	violations := runner_underutilized.violations with input as _run(8, 90.0, 18.0)
	count(violations) == 0
}

# A small runner is not oversized however little it does.
test_no_violation_on_a_small_runner if {
	violations := runner_underutilized.violations with input as _run(2, 12.0, 18.0)
	count(violations) == 0
}

test_no_violation_when_metrics_are_missing if {
	violations := runner_underutilized.violations with input as {"runner_specs": {"vcpus": 8}, "metrics": {}}
	count(violations) == 0
}

test_evidence_is_readable_for_whole_number_percentages if {
	violations := runner_underutilized.violations with input as _run(16, 10, 20)
	some v in violations
	v.evidence == "vCPUs=16, CPU=10%, RAM=20%"
}
