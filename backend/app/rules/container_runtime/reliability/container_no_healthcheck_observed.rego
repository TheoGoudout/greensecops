# METADATA
# title: Container ran without a healthcheck
# description: Measured runtime state shows the container had no healthcheck configured at all. The static missing_healthcheck rule reads the Dockerfile and the compose file; this observes the container that actually ran, so it also catches an image whose healthcheck was dropped by a compose override or by a base image that never declared one. Without a healthcheck, "running" is the only signal Docker can give, and a process that is up but not serving looks identical to one that works.
# custom:
#   severity: low
#   detection: dynamic_analysis
#   examples:
#     bad: |
#       containers: [{"name": "api", "has_healthcheck": false, "observed": true}]
#     good: |
#       containers: [{"name": "api", "has_healthcheck": true, "health_status": "healthy", "observed": true}]
#     fix: |
#       Add a HEALTHCHECK to the image or a healthcheck block to the compose service, probing a path the application actually serves. Dependents can then wait on service_healthy instead of racing the container's start.
package greensecops.container_runtime.reliability.container_no_healthcheck_observed

import rego.v1

violations contains violation if {
	some container in input.containers

	# A container the daemon never sampled tells us nothing about its
	# configuration — `has_healthcheck` would be a default, not a reading.
	container.observed == true
	container.has_healthcheck == false

	violation := {
		"rule": "container_no_healthcheck_observed",
		"severity": "low",
		"category": "reliability",
		"evidence": sprintf("container '%v' ran with no healthcheck configured", [container.name]),
		"recommendation": sprintf("Give '%v' a healthcheck that probes a served path, so dependents can wait on service_healthy rather than on the container merely being up.", [container.name]),
	}
}
