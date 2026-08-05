# METADATA
# title: Runner underutilized during the run
# description: Actual telemetry from a completed workflow run shows a large runner (8+ vCPUs) with low measured CPU and RAM usage throughout the job, indicating the runner size is not justified by the real workload — not just the declared job shape.
# custom:
#   severity: medium
#   detection: dynamic_analysis
#   examples:
#     bad: |
#       runner_specs: {"vcpus": 8}
#       metrics: {"cpu_load_percent": 12.0, "ram_percent": 18.0}
#     good: |
#       runner_specs: {"vcpus": 8}
#       metrics: {"cpu_load_percent": 71.0, "ram_percent": 64.0}
#     fix: |
#       Downsize the runner. Unlike the static runner_sizing check (which flags large runners with few workflow steps), this is measured, not inferred — the job actually ran and used little of the runner it was given.
package greensecops.ci_telemetry.energy.runner_underutilized

import rego.v1

_large_vcpu_threshold := 8

_low_cpu_threshold := 25.0

_low_ram_threshold := 30.0

violations contains violation if {
	vcpus := object.get(input.runner_specs, "vcpus", 0)
	vcpus >= _large_vcpu_threshold
	cpu_percent := object.get(input.metrics, "cpu_load_percent", 100.0)
	cpu_percent < _low_cpu_threshold
	ram_percent := object.get(input.metrics, "ram_percent", 100.0)
	ram_percent < _low_ram_threshold
	violation := {
		"rule": "runner_underutilized",
		"severity": "medium",
		"category": "energy",
		"evidence": sprintf("vCPUs=%v, CPU=%v%%, RAM=%v%%", [vcpus, round(cpu_percent), round(ram_percent)]),
		"recommendation": sprintf("Consider downsizing from %v vCPUs — measured usage during the run was low.", [vcpus]),
	}
}
