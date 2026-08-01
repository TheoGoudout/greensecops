# METADATA
# title: Deprecated MAINTAINER instruction
# description: The Dockerfile uses MAINTAINER, which Docker deprecated in 1.13 (2017) in favour of LABEL. It is kept only for backwards compatibility, no tooling reads it, and it is invisible to the OCI annotation conventions that registries and scanners actually consume.
# custom:
#   severity: low
#   detection: static_analysis
#   examples:
#     bad: |
#       MAINTAINER Platform Team <platform@example.com>
#     good: |
#       LABEL org.opencontainers.image.authors="Platform Team <platform@example.com>"
#     fix: |
#       Replace MAINTAINER with LABEL org.opencontainers.image.authors. While editing, consider adding org.opencontainers.image.source too — it is what links a published image back to the repository that built it.
package greensecops.container_docker.maintainability.maintainer_instruction_deprecated

import rego.v1

violations contains violation if {
	some df in input.dockerfiles
	some inst in df.instructions
	inst.instruction == "MAINTAINER"
	violation := {
		"rule": "maintainer_instruction_deprecated",
		"severity": "low",
		"category": "maintainability",
		"file_path": object.get(df, "__docker_file", ""),
		"line_start": object.get(inst, "__start_line__", null),
		"line_end": object.get(inst, "__end_line__", null),
		"message": "MAINTAINER is deprecated. Use LABEL org.opencontainers.image.authors instead.",
		"context": inst.value,
		"discriminator": inst.value,
	}
}
