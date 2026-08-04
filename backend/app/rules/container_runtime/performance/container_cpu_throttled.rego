# METADATA
# title: Container spent a large share of its scheduling periods throttled
# description: The kernel held the container at its CPU quota in a significant fraction of scheduling periods. Throttling is invisible in wall-clock metrics until it shows up as latency, and it is invisible to static analysis entirely — a quota is only wrong relative to what the workload tries to do.
# custom:
#   severity: medium
#   detection: dynamic_analysis
#   examples:
#     bad: |
#       containers: [{"name": "api", "cpu_throttled_percent": 42.0}]
#     good: |
#       containers: [{"name": "api", "cpu_throttled_percent": 2.0}]
#     fix: |
#       Raise the CPU quota, or lower the work the container attempts per period. Throttling is charged as latency on whatever request happened to be running, so it degrades the tail long before it shows up in an average.
package greensecops.container_runtime.performance.container_cpu_throttled

import rego.v1

# Occasional throttling is normal for a bursty workload and not worth a
# finding; a quarter of all periods is a quota the workload is fighting.
_throttled_percent_threshold := 25.0

violations contains violation if {
	some container in input.containers
	throttled := container.cpu_throttled_percent

	# Null is the reading for a container with no CPU quota at all — no quota
	# means nothing to throttle against, which is not this finding.
	is_number(throttled)
	throttled > _throttled_percent_threshold

	violation := {
		"rule": "container_cpu_throttled",
		"severity": "medium",
		"category": "performance",
		"evidence": sprintf("container '%v' was throttled in %v%% of its CPU scheduling periods", [container.name, round(throttled)]),
		"recommendation": sprintf("Raise the CPU quota for '%v' or reduce the work it attempts per period — throttling at this rate is paid as tail latency.", [container.name]),
	}
}
