# METADATA
# title: Compose service uses a floating image tag
# description: A service references an image with no tag, or with :latest. Two `docker compose up` runs a week apart then start different code, and a rollback to an older commit of the Compose file does not roll back the image it pulls.
# custom:
#   severity: medium
#   detection: static_analysis
#   examples:
#     bad: |
#       services:
#         cache:
#           image: redis
#     good: |
#       services:
#         cache:
#           image: redis:7.4-alpine
#     fix: |
#       Pin an explicit version tag, and a digest as well for anything running in production. Dependabot tracks both forms and will open PRs when a newer version ships.
package greensecops.container_docker.reliability.compose_unpinned_image_tag

import rego.v1

# A registry host may carry a port (`registry.example.com:5000/app`), so the
# tag can only be read from the last path segment.
_bare_name(image) := parts[count(parts) - 1] if {
	parts := split(image, "/")
}

_tag(image) := parts[1] if {
	parts := split(_bare_name(image), ":")
	count(parts) == 2
}

_unpinned(image) if not _tag(image)

_unpinned(image) if _tag(image) == "latest"

violations contains violation if {
	some cf in input.compose_files
	some name, service in cf.services
	is_object(service)
	image := service.image
	is_string(image)
	not contains(image, "@sha256:")
	_unpinned(image)
	violation := {
		"rule": "compose_unpinned_image_tag",
		"severity": "medium",
		"category": "reliability",
		"file_path": object.get(cf, "__docker_file", ""),
		"service_name": name,
		"line_start": object.get(service, "__start_line__", null),
		"line_end": object.get(service, "__end_line__", null),
		"message": sprintf("Service '%v' uses image '%v' with no fixed version, so repeated deploys are not reproducible.", [name, image]),
		"context": image,
		"discriminator": name,
	}
}
