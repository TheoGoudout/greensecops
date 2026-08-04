# METADATA
# title: One process used most of the CPU on a multi-core runner
# description: Per-process sampling shows a single process accounting for roughly one core's worth of work on a runner with several cores idle beside it. That is the signature of a step that cannot use the machine it was given — a single-threaded compiler, test runner or archiver. It matters because the usual response to a slow job, a bigger runner, buys nothing here; the fix is parallelism or a different tool.
# custom:
#   severity: medium
#   detection: dynamic_analysis
#   examples:
#     bad: |
#       runner_specs: {"vcpus": 8}
#       metrics:
#         cpu_load_percent: 14.0
#         top_processes: [{"pid": 900, "name": "tsc", "cpu_percent": 99.0, "mem_percent": 4.0, "mem_rss_mb": 620}]
#     good: |
#       runner_specs: {"vcpus": 8}
#       metrics:
#         cpu_load_percent: 76.0
#         top_processes: [{"pid": 900, "name": "tsc", "cpu_percent": 61.0, "mem_percent": 4.0, "mem_rss_mb": 620}]
#     fix: |
#       Give the step a parallel flag if it has one (-j, --workers, --parallel), or split its work across matrix jobs. If neither is possible, move it to a smaller runner — the extra cores are being paid for and not used.
package greensecops.ci_telemetry.performance.single_process_dominates_cpu

import rego.v1

# top_processes reports per-process CPU the way ps does: 100% is one core
# saturated, not the whole machine.
_one_core_percent := 90.0

# Overall load stays low precisely because the other cores are idle. Without
# this the rule would fire on a machine that is genuinely busy across all cores
# and merely has one hot process among many.
_low_overall_cpu := 50.0

_min_vcpus := 4

violations contains violation if {
	vcpus := object.get(input.runner_specs, "vcpus", 0)
	is_number(vcpus)
	vcpus >= _min_vcpus

	overall := object.get(input.metrics, "cpu_load_percent", 100.0)
	is_number(overall)
	overall < _low_overall_cpu

	some process in object.get(input.metrics, "top_processes", [])
	process_cpu := process.cpu_percent
	is_number(process_cpu)
	process_cpu >= _one_core_percent

	violation := {
		"rule": "single_process_dominates_cpu",
		"severity": "medium",
		"category": "performance",
		"evidence": sprintf("'%v' used %v%% CPU (about one core) while the %v-vCPU runner sat at %v%% overall", [process.name, round(process_cpu), vcpus, round(overall)]),
		"recommendation": sprintf("Parallelise '%v' if it supports it, or split its work across matrix jobs. A larger runner will not help a step that only uses one core.", [process.name]),
	}
}
