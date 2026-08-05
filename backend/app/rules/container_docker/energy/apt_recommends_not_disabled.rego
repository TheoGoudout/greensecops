# METADATA
# title: apt-get install pulls recommended packages
# description: An apt-get install runs without --no-install-recommends, so apt also installs everything the requested packages merely suggest. On a slim base this routinely triples what is fetched and shipped, and it is the reason a container that needs one CLI tool ends up with documentation, locales and sometimes an X11 stack. Every one of those is more to download on each pull, more to store, and more surface for a vulnerability scanner to find.
# custom:
#   severity: low
#   detection: pattern_matching
#   examples:
#     bad: |
#       FROM debian:13-slim
#       RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*
#     good: |
#       FROM debian:13-slim
#       RUN apt-get update \
#        && apt-get install -y --no-install-recommends curl \
#        && rm -rf /var/lib/apt/lists/*
#     fix: |
#       Add --no-install-recommends to the install, or set it once for the image with APT::Install-Recommends "false" in /etc/apt/apt.conf.d. If something then fails to work, name the package it actually needed rather than reverting.
package greensecops.container_docker.energy.apt_recommends_not_disabled

import rego.v1

_command_text(inst) := concat("\n", [part |
	some key in ["value", "heredoc"]
	part := object.get(inst, key, "")
	is_string(part)
	part != ""
])

_installs_with_apt(text) if regex.match(`(?i)\bapt(-get)?\s+(-[^\s]+\s+)*install\b`, text)

_disables_recommends(text) if contains(text, "--no-install-recommends")

# Setting it globally in apt.conf covers every later install in the image.
_disables_recommends(text) if {
	regex.match(`(?i)APT::Install-Recommends\s*"?(false|0)"?`, text)
}

violations contains violation if {
	some df in input.dockerfiles
	some inst in df.instructions
	inst.instruction == "RUN"
	text := _command_text(inst)
	_installs_with_apt(text)
	not _disables_recommends(text)

	# A global setting written by an earlier instruction applies here too.
	not _globally_disabled(df, inst)

	violation := {
		"rule": "apt_recommends_not_disabled",
		"severity": "low",
		"category": "energy",
		"file_path": object.get(df, "__docker_file", ""),
		"line_start": object.get(inst, "__start_line__", null),
		"line_end": object.get(inst, "__end_line__", null),
		"message": "This install also pulls apt's recommended packages, which on a slim base is usually most of what ends up in the image. Add --no-install-recommends.",
		"context": substring(text, 0, 300),
		"discriminator": text,
	}
}

_globally_disabled(df, inst) if {
	some earlier in df.instructions
	earlier.instruction == "RUN"
	earlier.stage == inst.stage
	earlier.__start_line__ < inst.__start_line__
	regex.match(`(?i)APT::Install-Recommends\s*"?(false|0)"?`, _command_text(earlier))
}
