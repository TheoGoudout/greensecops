# METADATA
# title: Secret hardcoded in a Compose environment
# description: A service's environment block sets a credential-looking variable to a literal value. Compose files are committed, so the value is in version-control history and is readable by anyone with repository access.
# custom:
#   severity: high
#   detection: pattern_matching
#   examples:
#     bad: |
#       services:
#         db:
#           image: postgres:17.2
#           environment:
#             POSTGRES_PASSWORD: 8Kf2mQx7Rv4Ld9Tn6Zb3Wc5Yh1Ap0Sj
#     good: |
#       services:
#         db:
#           image: postgres:17.2
#           environment:
#             POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?set in .env}
#     fix: |
#       Move the value into an untracked .env file and interpolate it, or use Compose secrets so it is mounted as a file rather than exposed in the container's environment. Rotate any credential that was committed — history keeps it even after the file is changed.
package greensecops.container_docker.security.compose_hardcoded_secret

import data.greensecops.lib.secrets
import rego.v1

_secret_name_pattern := `(?i)(API_?KEY|ACCESS_?KEY|SECRET|PASSWORD|PASSWD|TOKEN|CREDENTIAL|PRIVATE_?KEY)`

# `${VAR}` and `${VAR:-default}` are interpolations resolved at up time, not
# literals — the value is not in the file.
_is_interpolated(value) if contains(value, "${")

_is_interpolated(value) if startswith(value, "$")

# Compose accepts `environment` in two shapes and both are common in the wild.
# They are gathered by separate helpers, each guarded on the container type,
# because a single function may not produce two different outputs for the same
# input — and concatenating keeps one flat list for the rule body to walk.

# Mapping form: `environment: {KEY: value}`.
_mapping_pairs(service) := [[key, sprintf("%v", [value])] |
	is_object(service.environment)
	some key, value in service.environment
]

# List form: `environment: ["KEY=value"]`. Split on the *first* `=` only —
# requiring exactly two parts dropped every value containing one, which is
# every base64 secret with padding and every connection string.
_split_first(entry) := [trim_space(substring(entry, 0, eq)), substring(entry, eq + 1, -1)] if {
	eq := indexof(entry, "=")
	eq > 0
}

_list_pairs(service) := [pair |
	is_array(service.environment)
	some entry in service.environment
	is_string(entry)
	pair := _split_first(entry)
]

_pairs(service) := array.concat(_mapping_pairs(service), _list_pairs(service))

# Either half of the evidence is enough on its own: a recognised credential
# format needs no help from the variable name, and a long high-entropy literal
# under a secret-shaped name is a secret whatever format it is in.
_looks_like_a_credential(value) if secrets.known_credential(value)

_looks_like_a_credential(value) if {
	not secrets.is_placeholder(value)
	secrets.looks_high_entropy(value)
}

violations contains violation if {
	some cf in input.compose_files
	some name, service in cf.services
	is_object(service)
	some pair in _pairs(service)
	key := pair[0]
	value := pair[1]
	regex.match(_secret_name_pattern, key)
	value != ""
	not _is_interpolated(value)

	# The name alone is not evidence. Without a value-shape test this reported
	# `POSTGRES_PASSWORD: changethis` in a development Compose file as a leaked
	# credential — the same false positive `ci_workflow`'s `hardcoded_secrets`
	# was fixed for, using the same helpers it was fixed with.
	_looks_like_a_credential(value)
	violation := {
		"rule": "compose_hardcoded_secret",
		"severity": "high",
		"category": "security",
		"file_path": object.get(cf, "__docker_file", ""),
		"service_name": name,
		"line_start": object.get(service, "__start_line__", null),
		"line_end": object.get(service, "__end_line__", null),
		"message": sprintf("Service '%v' hardcodes %v in its environment. Interpolate it from .env or use a Compose secret, and rotate the credential.", [name, key]),
		"context": key,
		"discriminator": sprintf("%v:%v", [name, key]),
	}
}
