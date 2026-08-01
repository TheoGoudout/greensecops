# METADATA
# title: apt package lists left in the image
# description: A RUN instruction installs packages with apt-get but never removes /var/lib/apt/lists. The package index stays in that layer — typically 20-40 MB — and is pulled by every consumer of the image forever, for data that is stale the moment the layer is built.
# custom:
#   severity: low
#   detection: static_analysis
#   examples:
#     bad: |
#       RUN apt-get update && apt-get install -y curl
#     good: |
#       RUN apt-get update \
#        && apt-get install -y --no-install-recommends curl \
#        && rm -rf /var/lib/apt/lists/*
#     fix: |
#       Append `&& rm -rf /var/lib/apt/lists/*` to the same RUN instruction — a separate RUN does not help, because the files are already committed to the earlier layer. Alternatively mount the cache with `RUN --mount=type=cache,target=/var/lib/apt`, which keeps it out of the image entirely and speeds up rebuilds.
package greensecops.container_docker.energy.apt_cache_not_cleaned

import rego.v1

_installs_with_apt(text) if regex.match(`(?i)\bapt(-get)?\s+(-[^\s]+\s+)*install\b`, text)

_cleans_lists(text) if regex.match(`(?i)rm\s+-rf?\s+[^\n]*\/var\/lib\/apt\/lists`, text)

# A BuildKit cache mount keeps the index out of the layer altogether, which is
# the better fix — so a RUN that uses one is already correct.
_uses_cache_mount(inst) if {
	mount := object.get(inst, "flags", {}).mount
	contains(mount, "type=cache")
	regex.match(`/var/(lib|cache)/apt`, mount)
}

violations contains violation if {
	some df in input.dockerfiles
	some inst in df.instructions
	inst.instruction == "RUN"
	text := concat("\n", [part |
		some key in ["value", "heredoc"]
		part := object.get(inst, key, "")
		is_string(part)
	])
	_installs_with_apt(text)
	not _cleans_lists(text)
	not _uses_cache_mount(inst)
	violation := {
		"rule": "apt_cache_not_cleaned",
		"severity": "low",
		"category": "energy",
		"file_path": object.get(df, "__docker_file", ""),
		"line_start": object.get(inst, "__start_line__", null),
		"line_end": object.get(inst, "__end_line__", null),
		"message": "apt package lists are left in the image layer. Append '&& rm -rf /var/lib/apt/lists/*' to this RUN, or mount the cache instead.",
		"context": substring(text, 0, 300),
		"discriminator": text,
	}
}
