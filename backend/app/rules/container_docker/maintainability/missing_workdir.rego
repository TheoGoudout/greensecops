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

# The point of a WORKDIR is that something resolves a path against it. A stage
# whose COPY destinations are all absolute and whose RUNs never `cd` has
# nothing to resolve, which is the whole nginx/distroless shape — a file tree
# plus an absolute entrypoint. Treating any COPY as "relative work" reported
# `COPY --from=b /build/html /usr/share/nginx/html`, where both paths are
# absolute.

# The destination is the last token of a COPY/ADD in the shell form; the JSON
# form is a list, and its last element is the destination just the same.
_copy_destination(inst) := last if {
	tokens := [t | some t in regex.split(`\s+`, trim_space(trim(inst.value, "[]"))); t != ""]
	count(tokens) > 1
	last := trim(tokens[count(tokens) - 1], `"',`)
}

_has_relative_work(df) if {
	some inst in df.instructions
	inst.instruction in {"COPY", "ADD"}
	inst.stage == df.final_stage
	destination := _copy_destination(inst)
	not startswith(destination, "/")
}

# A script that changes directory, or names a path relative to the cwd. Any
# `cd` counts, absolute target included: `RUN cd /app && npm install` is
# precisely the thing a WORKDIR replaces, and it is the shape this rule is most
# useful on.
_has_relative_work(df) if {
	some inst in df.instructions
	inst.instruction == "RUN"
	inst.stage == df.final_stage
	regex.match(`(^|[;&|]\s*)cd\s|\./`, inst.value)
}

# A command argument that names a file resolves against the working directory.
# `["node", "server.js"]` does; `["nginx", "-g", "daemon off;"]` does not, and
# neither does an absolute `["/docker-entrypoint.sh"]`. The test is "looks like
# a path and is not absolute": a bare `/`, or a filename with an extension.
_names_a_relative_path(token) if {
	not startswith(token, "/")
	contains(token, "/")
}

_names_a_relative_path(token) if {
	not startswith(token, "/")
	regex.match(`^[A-Za-z0-9_.-]+\.[A-Za-z0-9]+$`, token)
}

_has_relative_work(df) if {
	some inst in df.instructions
	inst.instruction in {"CMD", "ENTRYPOINT"}
	inst.stage == df.final_stage
	some token in regex.split(`[\s,\[\]"']+`, inst.value)
	token != ""
	_names_a_relative_path(token)
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
