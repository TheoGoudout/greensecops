# METADATA
# title: Container image runs as root
# description: The final build stage declares no USER instruction, or sets it back to root, so the shipped image runs its entrypoint as uid 0. Any container escape or code-execution bug then starts with full root in the container namespace.
# custom:
#   severity: high
#   detection: static_analysis
#   examples:
#     bad: |
#       FROM node:22-slim
#       COPY . /app
#       CMD ["node", "/app/server.js"]
#     good: |
#       FROM node:22-slim
#       COPY . /app
#       RUN useradd --system --uid 10001 app
#       USER app
#       CMD ["node", "/app/server.js"]
#     fix: |
#       Create an unprivileged user and switch to it with USER before the CMD/ENTRYPOINT. Only the final stage matters — builder stages may stay root. If the process needs to bind a port below 1024, prefer a high port plus a published mapping over running as root.
package greensecops.container_docker.security.container_runs_as_root

import rego.v1

# Only the final stage ships. A builder stage legitimately runs as root to
# install toolchain packages, so scoping to `is_final` is what keeps this rule
# from firing on every multi-stage Dockerfile in existence.

_root_users := {"root", "0", "root:root", "0:0"}

_final_stage(df) := stage if {
	some stage in df.stages
	stage.is_final == true
}

_user_instructions(df) := [inst |
	some inst in df.instructions
	inst.instruction == "USER"
	inst.stage == df.final_stage
]

violations contains violation if {
	some df in input.dockerfiles
	stage := _final_stage(df)
	count(_user_instructions(df)) == 0
	violation := {
		"rule": "container_runs_as_root",
		"severity": "high",
		"category": "security",
		"file_path": object.get(df, "__docker_file", ""),
		"stage_name": object.get(stage, "name", null),
		"line_start": object.get(stage, "__start_line__", null),
		"line_end": object.get(stage, "__end_line__", null),
		"message": "The final build stage sets no USER, so the image runs as root. Add an unprivileged USER before the CMD/ENTRYPOINT.",
	}
}

violations contains violation if {
	some df in input.dockerfiles
	stage := _final_stage(df)
	users := _user_instructions(df)
	count(users) > 0
	last := users[count(users) - 1]
	lower(last.value) in _root_users
	violation := {
		"rule": "container_runs_as_root",
		"severity": "high",
		"category": "security",
		"file_path": object.get(df, "__docker_file", ""),
		"stage_name": object.get(stage, "name", null),
		"line_start": object.get(last, "__start_line__", null),
		"line_end": object.get(last, "__end_line__", null),
		"message": sprintf("The final build stage sets USER %v, so the image runs as root. Switch to an unprivileged user.", [last.value]),
		"context": last.value,
	}
}
