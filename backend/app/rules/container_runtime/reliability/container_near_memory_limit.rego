# METADATA
# title: Container peaked close to its memory limit
# description: Measured peak usage sits within a narrow margin of the declared limit. Nothing has failed yet, which is the point — this is the reading that precedes an OOM kill, and it is only visible before the fact from measurement.
# custom:
#   severity: medium
#   detection: dynamic_analysis
#   examples:
#     bad: |
#       containers: [{"name": "api", "peak_rss_bytes": 258000000, "mem_limit_bytes": 268435456, "oom_killed": false}]
#     good: |
#       containers: [{"name": "api", "peak_rss_bytes": 190000000, "mem_limit_bytes": 536870912, "oom_killed": false}]
#     fix: |
#       Raise the limit so the measured peak has room, or reduce what the workload retains. A margin this thin means the next slightly heavier request is the one that gets killed.
package greensecops.container_runtime.reliability.container_near_memory_limit

import rego.v1

# 90% of the limit. Tighter than this and normal variance between runs is
# enough to cross it.
_headroom_ratio := 0.9

violations contains violation if {
	some container in input.containers
	peak := container.peak_rss_bytes
	limit := container.mem_limit_bytes
	is_number(peak)
	is_number(limit)
	limit > 0
	peak > 0

	ratio := peak / limit
	ratio > _headroom_ratio

	# A container that was already OOM-killed is reported by
	# container_oom_killed, at a higher severity and with a fix that says the
	# same thing. Reporting both would double-count one problem.
	not container.oom_killed

	violation := {
		"rule": "container_near_memory_limit",
		"severity": "medium",
		"category": "reliability",
		"evidence": sprintf("container '%v' peaked at %v MB against a %v MB limit (%v%% of it)", [container.name, round(peak / 1000000), round(limit / 1000000), round(ratio * 100)]),
		"recommendation": sprintf("Raise '%v' above %v MB, or reduce what it retains — the current margin is too thin to absorb a heavier request.", [container.name, round(limit / 1000000)]),
	}
}
