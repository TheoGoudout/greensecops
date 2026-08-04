# METADATA
# title: Container exited with a non-zero status
# description: Measured runtime state shows the container's process ended with a failure status. A compose service that fails this way rarely fails the job with it — the workflow step that started the stack has already returned, so the exit code is only visible to whoever goes looking. It is the difference between a test suite that passed and one whose database was never up.
# custom:
#   severity: medium
#   detection: dynamic_analysis
#   examples:
#     bad: |
#       containers: [{"name": "migrate", "exit_code": 1}]
#     good: |
#       containers: [{"name": "migrate", "exit_code": 0}]
#     fix: |
#       Make the failure visible where it happens. If the container is a one-shot task, wait on it and propagate its status; if it is a service, give it a healthcheck and have dependents wait on the health condition rather than on the container merely existing.
package greensecops.container_runtime.reliability.container_nonzero_exit

import rego.v1

violations contains violation if {
	some container in input.containers
	code := container.exit_code

	# Null means the container was still running when the job ended, which is
	# the normal state for a long-lived service — not a failure.
	is_number(code)
	code != 0

	violation := {
		"rule": "container_nonzero_exit",
		"severity": "medium",
		"category": "reliability",
		"evidence": sprintf("container '%v' exited with status %v", [container.name, code]),
		"recommendation": sprintf("Check why '%v' failed, and make the failure surface in the job — a container that dies quietly still leaves whatever depended on it running against nothing.", [container.name]),
	}
}
