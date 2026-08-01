# METADATA
# title: Image declares no OCI source label
# description: The Dockerfile sets no org.opencontainers.image.source label, so a published image cannot be traced back to the repository that produced it. Registries, SBOM tooling and vulnerability scanners all read this annotation, and GitHub uses it to link a package to its repository.
# custom:
#   severity: low
#   detection: static_analysis
#   examples:
#     bad: |
#       FROM python:3.12-slim
#       COPY . /app
#     good: |
#       FROM python:3.12-slim
#       LABEL org.opencontainers.image.source="https://github.com/example/app"
#       LABEL org.opencontainers.image.licenses="Apache-2.0"
#       COPY . /app
#     fix: |
#       Add LABEL org.opencontainers.image.source pointing at the repository URL. The revision and created annotations are best injected at build time from CI rather than hardcoded, since they change every build.
package greensecops.container_docker.maintainability.missing_oci_labels

import rego.v1

_source_label := "org.opencontainers.image.source"

_final_stage(df) := stage if {
	some stage in df.stages
	stage.is_final == true
}

# A label set in any stage is inherited only if that stage is an ancestor of
# the final one, which cannot be resolved from the file alone — so this looks
# at the final stage, where the label unambiguously lands.
_has_source_label(df) if {
	some inst in df.instructions
	inst.instruction == "LABEL"
	inst.stage == df.final_stage
	contains(inst.value, _source_label)
}

violations contains violation if {
	some df in input.dockerfiles
	stage := _final_stage(df)
	not _has_source_label(df)
	violation := {
		"rule": "missing_oci_labels",
		"severity": "low",
		"category": "maintainability",
		"file_path": object.get(df, "__docker_file", ""),
		"stage_name": stage.name,
		"line_start": object.get(stage, "__start_line__", null),
		"line_end": object.get(stage, "__end_line__", null),
		"message": sprintf("No %v label, so the published image cannot be traced back to this repository.", [_source_label]),
		"discriminator": "oci-source-label",
	}
}
