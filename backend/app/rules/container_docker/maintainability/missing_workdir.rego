# METADATA
# title: Final stage never sets WORKDIR
# description: The shipped stage sets no working directory, so relative paths in its CMD, ENTRYPOINT and RUN instructions resolve against whatever the base image left — usually /, occasionally something else, and it can change when the base image is updated. Using `cd` in a RUN does not fix it either, since each instruction starts a new shell. The result is a Dockerfile whose correctness depends on a value it never states.
# custom:
#   severity: low
#   detection: static_analysis
#   examples:
#     bad: |
#       FROM node:22-slim
#       COPY . /app
#       CMD ["node", "server.js"]
#     good: |
#       FROM node:22-slim
#       WORKDIR /app
#       COPY . .
#       CMD ["node", "server.js"]
#     fix: |
#       Add a WORKDIR before the instructions that use relative paths. It creates the directory if it does not exist, so it also replaces the mkdir it usually sits next to.
package greensecops.container_docker.maintainability.missing_workdir

import rego.v1

_final_stage(df) := stage if {
	some stage in df.stages
	stage.is_final == true
}

_sets_workdir(df) if {
	some inst in df.instructions
	inst.instruction == "WORKDIR"
	inst.stage == df.final_stage
}

# A stage that runs nothing of its own has no relative paths to resolve. This
# is the scratch/distroless shape, where the image is a file tree plus an
# absolute entrypoint.
_has_relative_work(df) if {
	some inst in df.instructions
	inst.instruction in {"RUN", "CMD", "ENTRYPOINT", "COPY", "ADD"}
	inst.stage == df.final_stage
}

violations contains violation if {
	some df in input.dockerfiles
	stage := _final_stage(df)
	_has_relative_work(df)
	not _sets_workdir(df)

	violation := {
		"rule": "missing_workdir",
		"severity": "low",
		"category": "maintainability",
		"file_path": object.get(df, "__docker_file", ""),
		"stage_name": object.get(stage, "name", null),
		"line_start": object.get(stage, "__start_line__", null),
		"line_end": object.get(stage, "__end_line__", null),
		"message": "The final stage sets no WORKDIR, so relative paths resolve against whatever the base image happens to leave — a value this Dockerfile never states and the base image can change. Add a WORKDIR.",
	}
}
