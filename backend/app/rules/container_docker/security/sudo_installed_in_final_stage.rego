# METADATA
# title: sudo installed in the shipped image
# description: The final stage installs sudo. Combined with a USER instruction it usually means the image drops privileges and then hands back a way to regain them, which leaves the container effectively root with an extra step — and a sudoers rule of NOPASSWD, the usual companion, removes even that step. Nothing inside a container needs sudo, since a process that must run privileged can simply be the image's entrypoint and everything else can be done at build time while the build is still root.
# custom:
#   severity: low
#   detection: pattern_matching
#   examples:
#     bad: |
#       FROM debian:13-slim
#       RUN apt-get update && apt-get install -y sudo \
#        && useradd app && echo "app ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/app
#       USER app
#     good: |
#       FROM debian:13-slim
#       RUN useradd --system --uid 10001 app
#       USER app
#     fix: |
#       Do the privileged work in the build, before the USER instruction — the build runs as root already. If something genuinely must be privileged at runtime, give it its own container rather than a way for the application to escalate.
package greensecops.container_docker.security.sudo_installed_in_final_stage

import rego.v1

_command_text(inst) := concat("\n", [part |
	some key in ["value", "heredoc"]
	part := object.get(inst, key, "")
	is_string(part)
	part != ""
])

# Anchored on a package manager verb so a path containing "sudo", or a comment
# mentioning it, does not match.
_installs_sudo(text) if {
	regex.match(`(?i)\b(apt-get|apt|apk|yum|dnf|zypper)\b[^\n]*\b(install|add)\b[^\n]*\bsudo\b`, text)
}

violations contains violation if {
	some df in input.dockerfiles
	some inst in df.instructions
	inst.instruction == "RUN"

	# Only the final stage ships. A builder stage installing sudo is
	# discarded along with the rest of that stage.
	inst.stage == df.final_stage

	text := _command_text(inst)
	_installs_sudo(text)

	violation := {
		"rule": "sudo_installed_in_final_stage",
		"severity": "low",
		"category": "security",
		"file_path": object.get(df, "__docker_file", ""),
		"line_start": object.get(inst, "__start_line__", null),
		"line_end": object.get(inst, "__end_line__", null),
		"message": "sudo is installed in the shipped image, which gives a dropped-privilege container a way back to root. Do privileged work at build time instead, before the USER instruction.",
		"context": substring(text, 0, 300),
		"discriminator": text,
	}
}
