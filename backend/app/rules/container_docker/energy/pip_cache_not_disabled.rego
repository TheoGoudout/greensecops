# METADATA
# title: pip install leaves its wheel cache in the image
# description: A pip install runs without --no-cache-dir, so pip keeps every downloaded wheel under ~/.cache/pip inside the layer. The cache is useless in an image — nothing will install those packages again — but it is often comparable in size to the packages themselves, and for anything with compiled extensions it is considerably larger. Deleting it in a later instruction does not shrink the image, because the layer that wrote it is already fixed.
# custom:
#   severity: low
#   detection: pattern_matching
#   examples:
#     bad: |
#       FROM python:3.12-slim
#       COPY requirements.txt .
#       RUN pip install -r requirements.txt
#     good: |
#       FROM python:3.12-slim
#       COPY requirements.txt .
#       RUN pip install --no-cache-dir -r requirements.txt
#     fix: |
#       Add --no-cache-dir, or set PIP_NO_CACHE_DIR=1 once for the image. To keep the cache for build speed without shipping it, use a BuildKit cache mount instead — RUN --mount=type=cache,target=/root/.cache/pip.
package greensecops.container_docker.energy.pip_cache_not_disabled

import rego.v1

_command_text(inst) := concat("\n", [part |
	some key in ["value", "heredoc"]
	part := object.get(inst, key, "")
	is_string(part)
	part != ""
])

_installs_with_pip(text) if regex.match(`(?i)\b(pip3?|python3?\s+-m\s+pip)\b[^\n]*\binstall\b`, text)

_cache_disabled(text) if contains(text, "--no-cache-dir")

_cache_disabled(text) if regex.match(`(?i)PIP_NO_CACHE_DIR\s*=\s*["']?(1|true|on)`, text)

# A BuildKit cache mount keeps the cache outside the layer entirely, which is
# the better answer rather than a violation of this rule.
_uses_cache_mount(inst) if {
	mount := object.get(inst, "flags", {}).mount
	contains(mount, "type=cache")
	regex.match(`(?i)(\.cache/pip|/root/\.cache|pip)`, mount)
}

_env_disables_cache(df, inst) if {
	some earlier in df.instructions
	earlier.instruction == "ENV"
	earlier.stage == inst.stage
	earlier.__start_line__ < inst.__start_line__
	regex.match(`(?i)PIP_NO_CACHE_DIR\s*[= ]\s*["']?(1|true|on)`, earlier.value)
}

violations contains violation if {
	some df in input.dockerfiles
	some inst in df.instructions
	inst.instruction == "RUN"
	text := _command_text(inst)
	_installs_with_pip(text)
	not _cache_disabled(text)
	not _uses_cache_mount(inst)
	not _env_disables_cache(df, inst)

	violation := {
		"rule": "pip_cache_not_disabled",
		"severity": "low",
		"category": "energy",
		"file_path": object.get(df, "__docker_file", ""),
		"line_start": object.get(inst, "__start_line__", null),
		"line_end": object.get(inst, "__end_line__", null),
		"message": "pip keeps its downloaded wheels in the layer, where nothing will ever reuse them. Add --no-cache-dir, or mount the cache with --mount=type=cache to keep it out of the image.",
		"context": substring(text, 0, 300),
		"discriminator": text,
	}
}
