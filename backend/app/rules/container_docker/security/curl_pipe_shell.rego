# METADATA
# title: Remote script piped straight into a shell
# description: A RUN instruction downloads a script with curl or wget and pipes it directly into a shell. Nothing is verified before execution, so the build trusts whatever the remote host serves at build time — and the content can differ between the moment it is reviewed and the moment it runs.
# custom:
#   severity: high
#   detection: pattern_matching
#   examples:
#     bad: |
#       RUN curl -fsSL https://example.com/install.sh | sh
#     good: |
#       RUN curl -fsSL -o /tmp/install.sh https://example.com/install.sh \
#        && echo "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08  /tmp/install.sh" | sha256sum -c - \
#        && sh /tmp/install.sh \
#        && rm /tmp/install.sh
#     fix: |
#       Download to a file, verify it against a pinned checksum or signature, then execute it. Where the vendor publishes a package in a distro or language repository, prefer that over an install script.
package greensecops.container_docker.security.curl_pipe_shell

import rego.v1

# Both halves of a heredoc-style RUN matter: the instruction text carries the
# `<<EOF` marker while the commands live in the body, so a rule that only read
# `value` would miss every BuildKit heredoc.
_command_text(inst) := concat("\n", [part |
	some key in ["value", "heredoc"]
	part := object.get(inst, key, "")
	is_string(part)
	part != ""
])

_pipes_to_shell(text) if {
	regex.match(`(?i)(curl|wget)[^|;&]*\|\s*(sudo\s+)?(ba|z|k|da)?sh\b`, text)
}

violations contains violation if {
	some df in input.dockerfiles
	some inst in df.instructions
	inst.instruction == "RUN"
	text := _command_text(inst)
	_pipes_to_shell(text)
	violation := {
		"rule": "curl_pipe_shell",
		"severity": "high",
		"category": "security",
		"file_path": object.get(df, "__docker_file", ""),
		"line_start": object.get(inst, "__start_line__", null),
		"line_end": object.get(inst, "__end_line__", null),
		"message": "A remote script is piped straight into a shell. Download it, verify a checksum, then run it.",
		"context": substring(text, 0, 300),
		"discriminator": text,
	}
}
