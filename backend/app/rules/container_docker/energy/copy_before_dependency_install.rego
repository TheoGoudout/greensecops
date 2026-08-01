# METADATA
# title: Source copied before dependencies are installed
# description: A stage copies the whole build context before running its dependency install. Every layer after a COPY is invalidated when any copied file changes, so a one-character source edit re-downloads and rebuilds the entire dependency tree on every push — the single most expensive avoidable cost in a container build.
# custom:
#   severity: medium
#   detection: static_analysis
#   examples:
#     bad: |
#       FROM node:22-slim
#       WORKDIR /app
#       COPY . .
#       RUN npm ci
#     good: |
#       FROM node:22-slim
#       WORKDIR /app
#       COPY package.json package-lock.json ./
#       RUN npm ci
#       COPY . .
#     fix: |
#       Copy only the dependency manifests first (package-lock.json, requirements.txt, go.sum, Cargo.lock), run the install, then copy the rest of the source. The install layer is then reused on every build where dependencies did not change.
package greensecops.container_docker.energy.copy_before_dependency_install

import rego.v1

# Deliberately restricted to a copy of the *whole* context: copying a manifest
# or a subdirectory before installing is correct and common, and flagging it
# would make the rule useless noise.

_dependency_install_pattern := `(?i)(npm (ci|install)|yarn install|pnpm (install|i)\s|pip3? install|poetry install|uv sync|bundle install|go mod (download|tidy)|cargo fetch|composer install|mix deps\.get)`

_copies_whole_context(inst) if {
	inst.instruction in {"COPY", "ADD"}

	# `COPY --from=builder . /app` copies from an earlier stage, not the build
	# context, so it cannot be invalidated by a source edit.
	not object.get(inst, "flags", {}).from
	tokens := [token | some token in split(inst.value, " "); token != ""]
	count(tokens) >= 2
	tokens[0] in {".", "./"}
}

_installs_dependencies(inst) if {
	inst.instruction == "RUN"
	text := concat("\n", [part |
		some key in ["value", "heredoc"]
		part := object.get(inst, key, "")
		is_string(part)
	])
	regex.match(_dependency_install_pattern, text)
}

_broad_copy_indices(df, stage_index) := [i |
	some i, inst in df.instructions
	inst.stage == stage_index
	_copies_whole_context(inst)
]

_install_indices(df, stage_index) := [i |
	some i, inst in df.instructions
	inst.stage == stage_index
	_installs_dependencies(inst)
]

violations contains violation if {
	some df in input.dockerfiles
	some stage in df.stages
	copies := _broad_copy_indices(df, stage.index)
	installs := _install_indices(df, stage.index)
	count(copies) > 0
	count(installs) > 0
	copy_at := min(copies)
	install_at := min(installs)
	copy_at < install_at
	copy_inst := df.instructions[copy_at]
	install_inst := df.instructions[install_at]
	violation := {
		"rule": "copy_before_dependency_install",
		"severity": "medium",
		"category": "energy",
		"file_path": object.get(df, "__docker_file", ""),
		"stage_name": stage.name,
		"line_start": object.get(copy_inst, "__start_line__", null),
		"line_end": object.get(install_inst, "__end_line__", null),
		"message": sprintf("'%v %v' precedes the dependency install, so every source change rebuilds all dependencies. Copy the manifests first, install, then copy the source.", [copy_inst.instruction, copy_inst.value]),
		"context": install_inst.value,
		"discriminator": sprintf("stage:%v", [stage.index]),
	}
}
