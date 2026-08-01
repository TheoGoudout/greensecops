# METADATA
# title: Base image is not pinned
# description: A FROM instruction references an image by a floating tag (or no tag at all, which means :latest) rather than a digest. The same Dockerfile then produces different images over time, which breaks reproducibility and silently pulls in whatever the upstream publisher last pushed.
# custom:
#   severity: medium
#   detection: static_analysis
#   examples:
#     bad: |
#       FROM python:latest
#       FROM redis
#     good: |
#       FROM python:3.12-slim@sha256:0a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f9
#     fix: |
#       Pin the image by digest (image:tag@sha256:...). Keeping the human-readable tag alongside the digest is fine and makes updates reviewable. Dependabot understands the digest form and will raise PRs when the upstream tag moves.
package greensecops.container_docker.reliability.unpinned_base_image

import rego.v1

# A digest is the only immutable reference. A version tag is not one: `python`
# republishes `3.12` on every patch release, exactly as `actions/checkout`
# republishes `v4` — and ci_workflow/reliability/unpinned_actions already takes
# that position for Actions, so this rule takes the same one for base images.
#
# `FROM scratch` is the empty image — there is nothing to pin. A FROM naming an
# earlier stage (`FROM builder`) is an internal reference, not a registry pull,
# so neither is flagged.

_stage_names(df) := {name |
	some stage in df.stages
	name := stage.name
	name != null
}

_reference(stage) := sprintf("%v:%v", [stage.image, stage.tag]) if {
	stage.tag != null
} else := stage.image

violations contains violation if {
	some df in input.dockerfiles
	some stage in df.stages
	stage.digest == null
	stage.image != "scratch"
	not stage.image in _stage_names(df)
	violation := {
		"rule": "unpinned_base_image",
		"severity": "medium",
		"category": "reliability",
		"file_path": object.get(df, "__docker_file", ""),
		"stage_name": stage.name,
		"line_start": object.get(stage, "__start_line__", null),
		"line_end": object.get(stage, "__start_line__", null),
		"message": sprintf("Base image '%v' is not pinned to a digest, so this build is not reproducible.", [_reference(stage)]),
		"context": _reference(stage),
		"discriminator": sprintf("%v:%v", [stage.index, stage.image]),
	}
}
