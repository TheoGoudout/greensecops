# METADATA
# title: Container peaked at a very high process count
# description: Measured runtime state shows the container held an unusually large number of processes or threads at its peak. Without a pids limit the container can exhaust the host's process table, which takes down every other container on the runner rather than just this one. A high peak is also often a leak — a worker pool that spawns but never reaps — that a short CI job ends before it becomes visible.
# custom:
#   severity: low
#   detection: dynamic_analysis
#   examples:
#     bad: |
#       containers: [{"name": "worker", "peak_pids": 4200}]
#     good: |
#       containers: [{"name": "worker", "peak_pids": 64}]
#     fix: |
#       Set a pids_limit on the service so a runaway cannot reach the host's process table, then find what is spawning. A pool that grows without bound usually means workers are being created per unit of work instead of being reused.
package greensecops.container_runtime.reliability.container_pid_explosion

import rego.v1

# Docker's own default pids limit for a container is 4096 where one is applied
# at all. A peak in this range means the workload is within reach of it.
_pid_threshold := 1000

violations contains violation if {
	some container in input.containers
	pids := container.peak_pids

	# Null is the reading for a container that was never sampled.
	is_number(pids)
	pids > _pid_threshold

	violation := {
		"rule": "container_pid_explosion",
		"severity": "low",
		"category": "reliability",
		"evidence": sprintf("container '%v' peaked at %v processes", [container.name, pids]),
		"recommendation": sprintf("Set a pids_limit on '%v' and check whether the process count grows with the work rather than staying bounded.", [container.name]),
	}
}
