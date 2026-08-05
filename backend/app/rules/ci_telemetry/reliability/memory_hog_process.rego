# METADATA
# title: A single process held most of the runner's memory
# description: Per-process sampling shows one process holding a large share of the runner's RAM. The high_memory_pressure rule reports that the machine was close to the edge; this reports which process put it there, which is the part that determines what to do about it. A single process at this share is also the one the OOM-killer will pick, so it is the likeliest cause of a job that fails intermittently with no error of its own.
# custom:
#   severity: medium
#   detection: dynamic_analysis
#   examples:
#     bad: |
#       metrics:
#         ram_percent: 93.0
#         top_processes: [{"pid": 4100, "name": "jest", "cpu_percent": 40.0, "mem_percent": 71.0, "mem_rss_mb": 11400}]
#     good: |
#       metrics:
#         ram_percent: 48.0
#         top_processes: [{"pid": 4100, "name": "jest", "cpu_percent": 40.0, "mem_percent": 18.0, "mem_rss_mb": 2900}]
#     fix: |
#       Cap what the named process retains — most test runners and bundlers take a worker or heap limit. Running fewer workers in parallel usually costs less wall-clock time than an OOM kill and a re-run does.
package greensecops.ci_telemetry.reliability.memory_hog_process

import rego.v1

_dominant_memory_percent := 50.0

violations contains violation if {
	some process in object.get(input.metrics, "top_processes", [])
	mem_percent := process.mem_percent
	is_number(mem_percent)
	mem_percent >= _dominant_memory_percent

	violation := {
		"rule": "memory_hog_process",
		"severity": "medium",
		"category": "reliability",
		"evidence": sprintf("'%v' held %v%% of the runner's memory (%v MB)", [process.name, round(mem_percent), round(object.get(process, "mem_rss_mb", 0))]),
		"recommendation": sprintf("Cap what '%v' retains — a worker count or heap limit. It is the process the OOM-killer would choose, so it is the likeliest cause of an intermittent failure with no error of its own.", [process.name]),
	}
}
