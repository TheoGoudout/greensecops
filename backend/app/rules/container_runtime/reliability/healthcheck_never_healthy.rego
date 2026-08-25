# METADATA
# title: Container never reached a healthy state
# description: A healthcheck is defined but the container never passed it during the observed run. The static missing_healthcheck rule catches the absence of a check; this catches one that exists and never succeeds, which is worse — the orchestrator waits, retries and eventually gives up while the service looks configured correctly.
# custom:
#   severity: high
#   detection: dynamic_analysis
#   examples:
#     bad: |
#       containers: [{"name": "api", "has_healthcheck": true, "health_status": "unhealthy"}]
#     good: |
#       containers: [{"name": "api", "has_healthcheck": true, "health_status": "healthy"}]
#     fix: |
#       Check the probe actually exercises a path the service serves, and that --start-period is long enough to cover cold start — a probe that fires before the app finishes booting fails forever if the container is restarted each time.
package greensecops.container_runtime.reliability.healthcheck_never_healthy

import rego.v1

# `none` is deliberately absent. It was the default `object.get` fell back to,
# so a container whose health was never *reported* — telemetry gap, collector
# older than the field — was reported at high severity as having never become
# healthy. Missing data is not a failed healthcheck.
_unhealthy_states := {"unhealthy", "starting"}

violations contains violation if {
	some container in input.containers
	container.has_healthcheck == true
	is_string(container.health_status)
	status := lower(container.health_status)
	status in _unhealthy_states
	violation := {
		"rule": "healthcheck_never_healthy",
		"severity": "high",
		"category": "reliability",
		"evidence": sprintf("container '%v' ended the run in health state '%v'", [container.name, status]),
		"recommendation": "Verify the probe exercises a served path and that --start-period covers cold start.",
	}
}
