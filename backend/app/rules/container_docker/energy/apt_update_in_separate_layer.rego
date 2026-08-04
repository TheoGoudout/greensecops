# METADATA
# title: apt-get update in its own layer
# description: A RUN runs apt-get update without installing anything in the same instruction. The package index lands in its own layer, and Docker will happily reuse that cached layer for months while the install below it fetches versions the index no longer describes — the classic stale-cache build failure, which appears only on machines whose cache is old and not on the machine that wrote the Dockerfile. It also ships an index nothing needs.
# custom:
#   severity: medium
#   detection: pattern_matching
#   examples:
#     bad: |
#       FROM debian:13-slim
#       RUN apt-get update
#       RUN apt-get install -y --no-install-recommends curl
#     good: |
#       FROM debian:13-slim
#       RUN apt-get update \
#        && apt-get install -y --no-install-recommends curl \
#        && rm -rf /var/lib/apt/lists/*
#     fix: |
#       Join the update and the install into one RUN with &&, so they share a layer and are invalidated together. Clean /var/lib/apt/lists in the same instruction to keep the index out of the image.
package greensecops.container_docker.energy.apt_update_in_separate_layer

import rego.v1

_command_text(inst) := concat("\n", [part |
	some key in ["value", "heredoc"]
	part := object.get(inst, key, "")
	is_string(part)
	part != ""
])

_runs_update(text) if regex.match(`(?i)\bapt(-get)?\s+(-[^\s]+\s+)*update\b`, text)

_runs_install(text) if regex.match(`(?i)\bapt(-get)?\s+(-[^\s]+\s+)*install\b`, text)

violations contains violation if {
	some df in input.dockerfiles
	some inst in df.instructions
	inst.instruction == "RUN"
	text := _command_text(inst)
	_runs_update(text)
	not _runs_install(text)

	violation := {
		"rule": "apt_update_in_separate_layer",
		"severity": "medium",
		"category": "energy",
		"file_path": object.get(df, "__docker_file", ""),
		"line_start": object.get(inst, "__start_line__", null),
		"line_end": object.get(inst, "__end_line__", null),
		"message": "apt-get update runs without an install in the same RUN, so its cached layer can be reused long after the index is stale. Join it to the install with && and clean /var/lib/apt/lists in the same instruction.",
		"context": substring(text, 0, 300),
		"discriminator": text,
	}
}
