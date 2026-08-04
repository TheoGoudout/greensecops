# METADATA
# title: Container restarted repeatedly during the run
# description: Measured runtime state shows the container was restarted several times over the life of the job. A restart policy turns a crash into a retry, which is what makes this invisible — the service eventually comes up, the job passes, and nothing reports that it took four attempts. Repeated restarts are also pure waste, since every attempt re-runs whatever work the container had already done.
# custom:
#   severity: high
#   detection: dynamic_analysis
#   examples:
#     bad: |
#       containers: [{"name": "api", "restart_count": 5, "exit_code": 1}]
#     good: |
#       containers: [{"name": "api", "restart_count": 0, "exit_code": 0}]
#     fix: |
#       Read the container's logs from the first failed attempt rather than the last — the restart policy means the surviving logs are usually from an attempt that succeeded. Common causes are a dependency that is not ready yet (use depends_on with a health condition rather than a restart loop) and a config value that is missing on first boot.
package greensecops.container_runtime.reliability.container_restart_loop

import rego.v1

# One restart is a transient blip and a normal way for a service to wait out a
# dependency. Three is a pattern: something fails the same way every time.
_restart_threshold := 3

violations contains violation if {
	some container in input.containers
	restarts := container.restart_count

	# A container that was gone before the post step reports null, not 0.
	is_number(restarts)
	restarts >= _restart_threshold

	violation := {
		"rule": "container_restart_loop",
		"severity": "high",
		"category": "reliability",
		"evidence": sprintf("container '%v' restarted %v times during the run", [container.name, restarts]),
		"recommendation": sprintf("Investigate why '%v' exits — check the logs of its first attempt, not its last. A restart policy is masking a repeatable failure.", [container.name]),
	}
}
