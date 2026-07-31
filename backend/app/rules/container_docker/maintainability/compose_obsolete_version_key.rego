# METADATA
# title: Obsolete top-level version key in a Compose file
# description: The file declares a top-level version key. The Compose Specification dropped it, and current versions of Docker Compose print a warning on every invocation while ignoring the value. Keeping it suggests the file targets a schema that no longer exists.
# custom:
#   severity: low
#   detection: static_analysis
#   examples:
#     bad: |
#       version: "3.8"
#       services:
#         api:
#           image: ghcr.io/example/api:1.2.0
#     good: |
#       services:
#         api:
#           image: ghcr.io/example/api:1.2.0
#     fix: |
#       Delete the version line. Compose infers the schema from the fields in use, so nothing else needs to change.
package greensecops.container_docker.maintainability.compose_obsolete_version_key

import rego.v1

violations contains violation if {
	some cf in input.compose_files
	cf.version
	violation := {
		"rule": "compose_obsolete_version_key",
		"severity": "low",
		"category": "maintainability",
		"file_path": object.get(cf, "__docker_file", ""),
		"message": sprintf("The top-level 'version: %v' key is obsolete and ignored by Compose. Remove it.", [cf.version]),
		"context": sprintf("%v", [cf.version]),
		"discriminator": "version",
	}
}
