# METADATA
# title: Files made world-writable
# description: A RUN instruction grants write permission to everyone, usually as chmod 777. Once the image runs as a non-root user — which container_runs_as_root exists to encourage — a world-writable directory is exactly what lets a compromised process modify the application's own code and persist across a restart. The permission is almost always a workaround for a file-ownership mismatch that chown solves properly.
# custom:
#   severity: medium
#   detection: pattern_matching
#   examples:
#     bad: |
#       FROM python:3.12-slim
#       RUN mkdir /data && chmod -R 777 /data
#     good: |
#       FROM python:3.12-slim
#       RUN useradd --system --uid 10001 app \
#        && mkdir /data && chown app:app /data && chmod 750 /data
#     fix: |
#       Give the directory to the user the container runs as with chown, then use 750 or 755. World-writable is only ever needed when the owning uid is unknown at build time, and even then a named non-root user set with USER removes the need.
package greensecops.container_docker.security.chmod_world_writable

import rego.v1

_command_text(inst) := concat("\n", [part |
	some key in ["value", "heredoc"]
	part := object.get(inst, key, "")
	is_string(part)
	part != ""
])

# Octal forms whose last digit grants write to "other": 2, 3, 6, 7. Matching
# the digit rather than just 777 also catches 666 and 0777.
_world_writable(text) if {
	regex.match(`(?i)\bchmod\b[^\n]*\s0?[0-7][0-7][2367]\b`, text)
}

# The symbolic equivalent — chmod a+w, chmod o+w.
_world_writable(text) if {
	regex.match(`(?i)\bchmod\b[^\n]*\s[ao]*[+]w\b`, text)
}

violations contains violation if {
	some df in input.dockerfiles
	some inst in df.instructions
	inst.instruction == "RUN"
	text := _command_text(inst)
	_world_writable(text)

	violation := {
		"rule": "chmod_world_writable",
		"severity": "medium",
		"category": "security",
		"file_path": object.get(df, "__docker_file", ""),
		"line_start": object.get(inst, "__start_line__", null),
		"line_end": object.get(inst, "__end_line__", null),
		"message": "This makes files writable by every user in the container. Give the path to the user the container runs as with chown and use 750 or 755 instead.",
		"context": substring(text, 0, 300),
		"discriminator": text,
	}
}
