# METADATA
# title: Credential file copied into the image
# description: A COPY or ADD brings a file whose name marks it as a credential — an SSH private key, a PEM file, a cloud credentials directory, or an .npmrc/.netrc holding a registry token. Deleting it in a later instruction does not help, because the layer that added it stays in the image and anyone who can pull the image can read it back. This is how private deploy keys most often escape.
# custom:
#   severity: high
#   detection: pattern_matching
#   examples:
#     bad: |
#       FROM node:22-slim
#       COPY .npmrc /root/.npmrc
#       RUN npm ci && rm /root/.npmrc
#     good: |
#       FROM node:22-slim
#       RUN --mount=type=secret,id=npmrc,target=/root/.npmrc npm ci
#     fix: |
#       Use a BuildKit secret mount (RUN --mount=type=secret), which makes the file available for one instruction without ever writing it to a layer. For an SSH key specifically, --mount=type=ssh forwards the agent instead of the key. Add the path to .dockerignore so it cannot be copied in by a wildcard either.
package greensecops.container_docker.security.secret_file_copied

import rego.v1

# Matched on the source path only. Each pattern names a file that has no
# legitimate reason to be inside an image, rather than anything merely
# sensitive-sounding — "config" and "key" alone produce far too much noise.
_secret_path_patterns := [
	`(?i)(^|[\s/])id_(rsa|dsa|ecdsa|ed25519)($|\s)`,
	`(?i)\.pem($|\s)`,
	`(?i)\.p12($|\s)`,
	`(?i)\.pfx($|\s)`,
	`(?i)(^|[\s/])\.ssh(/|\s|$)`,
	`(?i)(^|[\s/])\.aws(/|\s|$)`,
	`(?i)(^|[\s/])\.npmrc($|\s)`,
	`(?i)(^|[\s/])\.netrc($|\s)`,
	`(?i)(^|[\s/])\.git-credentials($|\s)`,
	`(?i)(^|[\s/])service[-_]account.*\.json($|\s)`,
]

# COPY/ADD take "src... dest", so everything but the last token is a source.
# A destination named .npmrc is not itself the problem — what was copied is.
_sources(inst) := array.slice(parts, 0, count(parts) - 1) if {
	parts := regex.split(`\s+`, trim_space(inst.value))
	count(parts) > 1
}

_is_secret_path(path) if {
	some pattern in _secret_path_patterns
	regex.match(pattern, path)
}

violations contains violation if {
	some df in input.dockerfiles
	some inst in df.instructions
	inst.instruction in {"COPY", "ADD"}

	# A COPY --from=builder moves a file between stages of this build; it is
	# not reaching into the build context for a developer's credentials.
	not object.get(inst, "flags", {}).from

	some source in _sources(inst)
	_is_secret_path(source)

	violation := {
		"rule": "secret_file_copied",
		"severity": "high",
		"category": "security",
		"file_path": object.get(df, "__docker_file", ""),
		"line_start": object.get(inst, "__start_line__", null),
		"line_end": object.get(inst, "__end_line__", null),
		"message": sprintf("'%v' is copied into the image. Removing it later does not help — the layer that added it keeps the file, and anyone who can pull the image can read it. Use a BuildKit secret mount instead.", [source]),
		"context": inst.value,
		"discriminator": source,
	}
}
