package greensecops.ci_telemetry.reliability.memory_hog_process_test

import data.greensecops.ci_telemetry.reliability.memory_hog_process
import rego.v1

_process(name, mem_percent, rss) := {
	"pid": 4100,
	"name": name,
	"cpu_percent": 40.0,
	"mem_percent": mem_percent,
	"mem_rss_mb": rss,
}

_metrics(processes) := {"runner_specs": {"vcpus": 4}, "metrics": {"top_processes": processes}}

test_violation_when_one_process_holds_most_of_the_memory if {
	violations := memory_hog_process.violations with input as _metrics([_process("jest", 71.0, 11400)])
	count(violations) == 1
	some v in violations
	contains(v.evidence, "jest")
	contains(v.evidence, "11400 MB")
}

test_violation_exactly_at_the_threshold if {
	violations := memory_hog_process.violations with input as _metrics([_process("jest", 50.0, 8000)])
	count(violations) == 1
}

test_no_violation_below_the_threshold if {
	violations := memory_hog_process.violations with input as _metrics([_process("jest", 18.0, 2900)])
	count(violations) == 0
}

# top_processes is Linux-only; its absence must not be read as a finding.
test_no_violation_when_top_processes_is_absent if {
	violations := memory_hog_process.violations with input as {"runner_specs": {}, "metrics": {"ram_percent": 93.0}}
	count(violations) == 0
}

test_no_violation_when_a_memory_reading_is_null if {
	violations := memory_hog_process.violations with input as _metrics([_process("jest", null, 11400)])
	count(violations) == 0
}

test_each_hogging_process_is_its_own_finding if {
	violations := memory_hog_process.violations with input as _metrics([
		_process("jest", 55.0, 8800),
		_process("tsc", 61.0, 9700),
		_process("node", 4.0, 640),
	])
	count(violations) == 2
}

test_evidence_falls_back_when_rss_is_missing if {
	violations := memory_hog_process.violations with input as _metrics([{
		"pid": 1,
		"name": "jest",
		"mem_percent": 88.0,
	}])
	count(violations) == 1
	some v in violations
	contains(v.evidence, "0 MB")
}
