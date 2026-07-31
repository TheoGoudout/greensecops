# METADATA
# title: Runnable image declares no HEALTHCHECK
# description: The final stage defines a CMD or ENTRYPOINT but no HEALTHCHECK, so the runtime can only tell whether the process is alive — not whether it is serving. A process that is deadlocked, wedged on a dependency, or listening but failing every request looks perfectly healthy, and orchestrators route traffic to it.
# custom:
#   severity: medium
#   detection: static_analysis
#   examples:
#     bad: |
#       FROM nginx:1.27-alpine
#       COPY site /usr/share/nginx/html
#       CMD ["nginx", "-g", "daemon off;"]
#     good: |
#       FROM nginx:1.27-alpine
#       COPY site /usr/share/nginx/html
#       HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
#         CMD wget -qO- http://localhost/ || exit 1
#       CMD ["nginx", "-g", "daemon off;"]
#     fix: |
#       Add a HEALTHCHECK that exercises the path the service actually serves, not just a TCP connect. Set --start-period generously enough to cover cold start, or the container will be restarted mid-boot. Where the orchestrator owns health probes (Kubernetes readiness probes, Compose healthcheck blocks), defining it there instead is equally valid.
package greensecops.container_docker.reliability.missing_healthcheck

import rego.v1

# Scoped to images that actually run something: a base or toolchain image with
# no CMD/ENTRYPOINT has nothing to health-check, and flagging it would be noise.

_final_stage(df) := stage if {
	some stage in df.stages
	stage.is_final == true
}

_final_instructions(df) := [inst |
	some inst in df.instructions
	inst.stage == df.final_stage
]

_is_runnable(df) if {
	some inst in _final_instructions(df)
	inst.instruction in {"CMD", "ENTRYPOINT"}
}

_has_healthcheck(df) if {
	some inst in _final_instructions(df)
	inst.instruction == "HEALTHCHECK"
	lower(inst.value) != "none"
}

violations contains violation if {
	some df in input.dockerfiles
	stage := _final_stage(df)
	_is_runnable(df)
	not _has_healthcheck(df)
	violation := {
		"rule": "missing_healthcheck",
		"severity": "medium",
		"category": "reliability",
		"file_path": object.get(df, "__docker_file", ""),
		"stage_name": stage.name,
		"line_start": object.get(stage, "__start_line__", null),
		"line_end": object.get(stage, "__end_line__", null),
		"message": "The final stage runs a process but declares no HEALTHCHECK, so the runtime cannot tell a wedged container from a healthy one.",
		"discriminator": "final-stage-healthcheck",
	}
}
