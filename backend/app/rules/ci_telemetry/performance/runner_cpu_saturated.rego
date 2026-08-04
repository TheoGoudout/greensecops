# METADATA
# title: Runner ran pinned at full CPU
# description: Measured telemetry shows the runner's CPU essentially saturated for the run. This is the mirror image of runner_underutilized — the workload wanted more machine than it was given, so wall-clock time is being spent queueing rather than computing, and every job behind this one waits for it. A saturated small runner is often cheaper to fix by resizing than by optimising.
# custom:
#   severity: medium
#   detection: dynamic_analysis
#   examples:
#     bad: |
#       runner_specs: {"vcpus": 2}
#       metrics: {"cpu_load_percent": 98.0}
#     good: |
#       runner_specs: {"vcpus": 4}
#       metrics: {"cpu_load_percent": 68.0}
#     fix: |
#       Give the job more vCPUs, or reduce what it does per run. Check first whether the work is actually parallel — a saturated runner with one busy process (see single_process_dominates_cpu) will not go faster on a bigger machine.
package greensecops.ci_telemetry.performance.runner_cpu_saturated

import rego.v1

_saturated_cpu_threshold := 95.0

# A large runner at full tilt is doing what it was sized for. This is about a
# machine too small for its job, so it does not fire where runner_sizing and
# runner_underutilized already look.
_max_vcpus := 8

violations contains violation if {
	cpu_percent := object.get(input.metrics, "cpu_load_percent", 0)
	is_number(cpu_percent)
	cpu_percent >= _saturated_cpu_threshold

	vcpus := object.get(input.runner_specs, "vcpus", 0)
	is_number(vcpus)
	vcpus < _max_vcpus

	violation := {
		"rule": "runner_cpu_saturated",
		"severity": "medium",
		"category": "performance",
		"evidence": sprintf("CPU was at %v%% on a %v-vCPU runner", [round(cpu_percent), vcpus]),
		"recommendation": sprintf("Size the job above %v vCPUs, or cut what it does per run. Check the work is genuinely parallel first — a bigger runner does not help a single-threaded step.", [vcpus]),
	}
}
