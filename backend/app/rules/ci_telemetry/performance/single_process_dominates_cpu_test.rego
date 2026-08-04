package greensecops.ci_telemetry.performance.single_process_dominates_cpu_test

import data.greensecops.ci_telemetry.performance.single_process_dominates_cpu as dominates
import rego.v1

# top_processes comes from the Linux-only proc-sampler binary and is absent on
# other platforms or when the binary is unavailable. Per-process cpu_percent is
# ps-style: 100% means one saturated core, not the whole machine.

_process(name, cpu) := {
	"pid": 900,
	"name": name,
	"cpu_percent": cpu,
	"mem_percent": 4.0,
	"mem_rss_mb": 620,
}

_run(vcpus, overall, processes) := {
	"runner_specs": {"vcpus": vcpus},
	"metrics": {"cpu_load_percent": overall, "top_processes": processes},
}

test_violation_when_one_process_holds_a_core_on_an_idle_runner if {
	violations := dominates.violations with input as _run(8, 14.0, [_process("tsc", 99.0)])
	count(violations) == 1
	some v in violations
	contains(v.evidence, "tsc")
	contains(v.recommendation, "tsc")
}

# The whole point is that the *rest* of the machine is idle. A busy runner with
# one hot process among many is using what it was given.
test_no_violation_when_the_runner_is_busy_overall if {
	violations := dominates.violations with input as _run(8, 76.0, [_process("tsc", 99.0)])
	count(violations) == 0
}

test_no_violation_when_no_process_saturates_a_core if {
	violations := dominates.violations with input as _run(8, 20.0, [_process("tsc", 61.0)])
	count(violations) == 0
}

# On a small runner there are no spare cores to be wasting.
test_no_violation_on_a_small_runner if {
	violations := dominates.violations with input as _run(2, 40.0, [_process("tsc", 99.0)])
	count(violations) == 0
}

test_no_violation_when_top_processes_is_absent if {
	violations := dominates.violations with input as {
		"runner_specs": {"vcpus": 8},
		"metrics": {"cpu_load_percent": 14.0},
	}
	count(violations) == 0
}

test_no_violation_when_top_processes_is_empty if {
	violations := dominates.violations with input as _run(8, 14.0, [])
	count(violations) == 0
}

test_no_violation_when_a_process_cpu_reading_is_null if {
	violations := dominates.violations with input as _run(8, 14.0, [_process("tsc", null)])
	count(violations) == 0
}

test_each_dominating_process_is_its_own_finding if {
	violations := dominates.violations with input as _run(16, 22.0, [
		_process("tsc", 99.0),
		_process("webpack", 97.0),
		_process("node", 12.0),
	])
	count(violations) == 2
}
