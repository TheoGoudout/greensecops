# METADATA
# title: Final image uses a full-fat base
# description: The final stage builds on a full distribution or full language image where the publisher also ships a slim variant. The difference is typically several hundred megabytes of packages the application never calls, paid on every pull, every registry push and every byte stored.
# custom:
#   severity: low
#   detection: heuristic
#   examples:
#     bad: |
#       FROM python:3.12
#     good: |
#       FROM python:3.12-slim
#     fix: |
#       Switch to the -slim variant and add back only what the application actually needs. Verify before adopting -alpine: it uses musl rather than glibc, which changes behaviour for some binary wheels and can make builds slower, so slim is usually the safer first move.
package greensecops.container_docker.energy.heavy_base_image

import rego.v1

# An explicit list, not a general heuristic: "this image is bigger than it
# needs to be" is an opinion, and the rule is only defensible where the same
# publisher offers a documented smaller variant of the same image.
_slimmable := {"ubuntu", "debian", "python", "node", "ruby", "openjdk"}

_slim_markers := ["slim", "alpine", "jre", "distroless", "-minimal"]

# Only the final stage ships. A builder on a full image is the right choice.
_final_stage(df) := stage if {
	some stage in df.stages
	stage.is_final == true
}

# `docker.io/library/python` and `python` are the same image.
_bare_name(image) := parts[count(parts) - 1] if {
	parts := split(image, "/")
}

_is_slim(tag) if {
	some marker in _slim_markers
	contains(lower(tag), marker)
}

violations contains violation if {
	some df in input.dockerfiles
	stage := _final_stage(df)
	_bare_name(stage.image) in _slimmable
	tag := object.get(stage, "tag", null)
	tag != null
	not _is_slim(tag)
	violation := {
		"rule": "heavy_base_image",
		"severity": "low",
		"category": "energy",
		"file_path": object.get(df, "__docker_file", ""),
		"stage_name": stage.name,
		"line_start": object.get(stage, "__start_line__", null),
		"line_end": object.get(stage, "__start_line__", null),
		"message": sprintf("Final image is built on '%v:%v', which ships a full distribution. A -slim variant of the same image is usually a drop-in replacement.", [stage.image, tag]),
		"context": sprintf("%v:%v", [stage.image, tag]),
		"discriminator": "final-stage-base",
	}
}
