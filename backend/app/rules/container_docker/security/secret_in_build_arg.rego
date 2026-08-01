# METADATA
# title: Secret hardcoded in ARG or ENV
# description: An ARG or ENV instruction whose name looks like a credential is given a literal default value. Build arguments and environment variables are recorded in the image metadata and are readable by anyone who can pull the image, so the value must be treated as disclosed.
# custom:
#   severity: critical
#   detection: pattern_matching
#   examples:
#     bad: |
#       ARG NPM_TOKEN=npm_A1b2C3d4E5f6
#       ENV DB_PASSWORD=hunter2
#     good: |
#       ARG NPM_TOKEN
#       RUN --mount=type=secret,id=npm_token \
#           NPM_TOKEN="$(cat /run/secrets/npm_token)" npm ci
#     fix: |
#       Drop the literal default. Pass build-time credentials with BuildKit secret mounts (RUN --mount=type=secret), which never land in a layer, and inject runtime credentials from the orchestrator rather than baking them into ENV. Rotate any value that was previously committed — it must be considered compromised.
package greensecops.container_docker.security.secret_in_build_arg

import rego.v1

_secret_name_pattern := `(?i)(API_?KEY|ACCESS_?KEY|SECRET|PASSWORD|PASSWD|TOKEN|CREDENTIAL|PRIVATE_?KEY)`

# `KEY=value` pairs, quoted or bare. The legacy `ENV KEY value` form is not
# matched: without an `=` there is no reliable way to tell a value from the
# next key, and every modern Dockerfile uses the `=` form.
_assignments(text) := [[pair[1], trim(pair[2], `"'`)] |
	some pair in regex.find_all_string_submatch_n(`([A-Za-z_][A-Za-z0-9_]*)=("[^"]*"|'[^']*'|[^\s]+)`, text, -1)
]

# A value that dereferences another variable or a mounted secret is not a
# literal — `ENV PASSWORD=$DB_PASSWORD` discloses nothing on its own.
_is_reference(value) if startswith(value, "$")

violations contains violation if {
	some df in input.dockerfiles
	some inst in df.instructions
	inst.instruction in {"ARG", "ENV"}
	some assignment in _assignments(inst.value)
	name := assignment[0]
	value := assignment[1]
	regex.match(_secret_name_pattern, name)
	value != ""
	not _is_reference(value)
	violation := {
		"rule": "secret_in_build_arg",
		"severity": "critical",
		"category": "security",
		"file_path": object.get(df, "__docker_file", ""),
		"line_start": object.get(inst, "__start_line__", null),
		"line_end": object.get(inst, "__end_line__", null),
		"message": sprintf("%v %v has a hardcoded value and is baked into the image metadata. Remove it and rotate the credential.", [inst.instruction, name]),
		"context": name,
		"discriminator": name,
	}
}
