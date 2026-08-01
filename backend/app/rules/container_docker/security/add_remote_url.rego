# METADATA
# title: ADD used to fetch a remote URL
# description: An ADD instruction takes a remote URL as its source. ADD fetches over the network with no checksum verification and no way to inspect what arrived before it lands in a layer, and it silently auto-extracts archives.
# custom:
#   severity: medium
#   detection: static_analysis
#   examples:
#     bad: |
#       ADD https://example.com/app.tar.gz /opt/app.tar.gz
#     good: |
#       RUN curl -fsSL -o /opt/app.tar.gz https://example.com/app.tar.gz \
#        && echo "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08  /opt/app.tar.gz" | sha256sum -c -
#     fix: |
#       Replace ADD with an explicit RUN that downloads and verifies a checksum, or use ADD with its --checksum flag (BuildKit). Reserve ADD for local archives you want auto-extracted, and COPY for everything else.
package greensecops.container_docker.security.add_remote_url

import rego.v1

_remote_prefixes := ["http://", "https://", "git@", "github.com/"]

_sources(inst) := [token |
	some token in split(inst.value, " ")
	token != ""
]

_is_remote(token) if {
	some prefix in _remote_prefixes
	startswith(lower(token), prefix)
}

violations contains violation if {
	some df in input.dockerfiles
	some inst in df.instructions
	inst.instruction == "ADD"

	# BuildKit's --checksum makes a remote ADD verifiable, which is the whole
	# objection — so an ADD that has one is accepted.
	not object.get(inst, "flags", {}).checksum
	some token in _sources(inst)
	_is_remote(token)
	violation := {
		"rule": "add_remote_url",
		"severity": "medium",
		"category": "security",
		"file_path": object.get(df, "__docker_file", ""),
		"line_start": object.get(inst, "__start_line__", null),
		"line_end": object.get(inst, "__end_line__", null),
		"message": sprintf("ADD fetches '%v' over the network without verification. Use RUN with a checksum, or ADD --checksum.", [token]),
		"context": token,
		"discriminator": token,
	}
}
