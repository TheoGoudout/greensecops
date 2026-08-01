# METADATA
# title: Build toolchain shipped in a single-stage image
# description: A single-stage Dockerfile installs a compiler or build toolchain, so those packages — and everything they pull in — ship in the final image. They are needed to produce the artifact and never to run it, and they inflate every pull, every layer push and every byte stored in the registry.
# custom:
#   severity: medium
#   detection: static_analysis
#   examples:
#     bad: |
#       FROM python:3.12-slim
#       RUN apt-get update && apt-get install -y build-essential
#       RUN pip install -r requirements.txt
#       CMD ["python", "app.py"]
#     good: |
#       FROM python:3.12-slim AS builder
#       RUN apt-get update && apt-get install -y build-essential
#       RUN pip install --prefix=/install -r requirements.txt
#
#       FROM python:3.12-slim
#       COPY --from=builder /install /usr/local
#       CMD ["python", "app.py"]
#     fix: |
#       Split the build into stages: install the toolchain and compile in a builder stage, then COPY --from=builder only the produced artifact into a clean final stage. The toolchain never reaches the published image.
package greensecops.container_docker.energy.no_multistage_build

import rego.v1

# Restricted to an explicit toolchain list rather than a general "this looks
# like a build" heuristic. A false positive here asks someone to restructure a
# whole Dockerfile, so the bar for firing is a package that is unambiguously
# build-time only.
_toolchain_pattern := `(?i)(build-essential|\bgcc\b|\bg\+\+\b|\bmake\b|\bcmake\b|automake|libtool|\bmaven\b|\bgradle\b|openjdk-[0-9]+-jdk|python3?-dev|libffi-dev|libssl-dev)`

_installs_toolchain(inst) if {
	inst.instruction == "RUN"
	text := concat("\n", [part |
		some key in ["value", "heredoc"]
		part := object.get(inst, key, "")
		is_string(part)
	])
	regex.match(_toolchain_pattern, text)
}

violations contains violation if {
	some df in input.dockerfiles
	count(df.stages) == 1
	some inst in df.instructions
	_installs_toolchain(inst)
	violation := {
		"rule": "no_multistage_build",
		"severity": "medium",
		"category": "energy",
		"file_path": object.get(df, "__docker_file", ""),
		"stage_name": df.stages[0].name,
		"line_start": object.get(inst, "__start_line__", null),
		"line_end": object.get(inst, "__end_line__", null),
		"message": "A build toolchain is installed in a single-stage image, so it ships to every consumer. Move the build into a builder stage and COPY --from it.",
		"context": substring(inst.value, 0, 300),
		"discriminator": "single-stage-toolchain",
	}
}
