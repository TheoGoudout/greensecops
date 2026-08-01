# METADATA
# title: Container was OOM-killed
# description: Measured runtime state shows the kernel terminated the container for exceeding its memory limit. The static compose_missing_resource_limits check flags the absence of a limit; this one observes a limit that exists and is too low, or a workload that genuinely needs more than it was given.
# custom:
#   severity: high
#   detection: dynamic_analysis
#   examples:
#     bad: |
#       containers: [{"name": "worker", "oom_killed": true, "mem_limit_bytes": 268435456}]
#     good: |
#       containers: [{"name": "worker", "oom_killed": false, "peak_rss_bytes": 190000000, "mem_limit_bytes": 536870912}]
#     fix: |
#       Raise the limit to cover measured peak usage with headroom, or find what is retaining memory. An OOM kill is a hard stop mid-request — the restart policy hides it from dashboards without making it harmless.
package greensecops.container_runtime.reliability.container_oom_killed

import rego.v1

violations contains violation if {
	some container in input.containers
	container.oom_killed == true
	violation := {
		"rule": "container_oom_killed",
		"severity": "high",
		"category": "reliability",
		"evidence": sprintf("container '%v' was OOM-killed", [container.name]),
		"recommendation": "Raise the memory limit to cover measured peak usage with headroom, or investigate what is retaining memory.",
	}
}
