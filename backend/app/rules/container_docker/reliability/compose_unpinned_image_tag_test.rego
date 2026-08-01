package greensecops.container_docker.reliability.compose_unpinned_image_tag_test

import data.greensecops.container_docker.reliability.compose_unpinned_image_tag
import rego.v1

_compose(services) := {"compose_files": [{
	"__docker_file": "compose.yml",
	"services": services,
}]}

_service(image) := {"image": image, "__start_line__": 2, "__end_line__": 4}

test_violation_when_no_tag if {
	violations := compose_unpinned_image_tag.violations with input as _compose({"cache": _service("redis")})
	count(violations) == 1
}

test_violation_when_tag_is_latest if {
	violations := compose_unpinned_image_tag.violations with input as _compose({"cache": _service("redis:latest")})
	count(violations) == 1
}

test_no_violation_with_a_version_tag if {
	violations := compose_unpinned_image_tag.violations with input as _compose({"cache": _service("redis:7.4-alpine")})
	count(violations) == 0
}

test_no_violation_when_pinned_by_digest if {
	violations := compose_unpinned_image_tag.violations with input as _compose({"cache": _service("redis@sha256:abc123")})
	count(violations) == 0
}

# A registry port must not be mistaken for a tag.
test_violation_for_registry_with_port_and_no_tag if {
	violations := compose_unpinned_image_tag.violations with input as _compose({"cache": _service("registry.example.com:5000/redis")})
	count(violations) == 1
}

test_no_violation_for_registry_with_port_and_a_tag if {
	violations := compose_unpinned_image_tag.violations with input as _compose({"cache": _service("registry.example.com:5000/redis:7.4")})
	count(violations) == 0
}

# A build-only service has no image to pin.
test_no_violation_for_build_only_service if {
	violations := compose_unpinned_image_tag.violations with input as _compose({"api": {"build": {"context": "."}, "__start_line__": 2, "__end_line__": 4}})
	count(violations) == 0
}

# A service that also builds is naming its own build output; the digest does
# not exist until the build runs, so there is nothing to pin.
test_no_violation_when_the_service_builds_the_image_it_names if {
	violations := compose_unpinned_image_tag.violations with input as _compose({"backend": {
		"image": "greensecops/backend:${TAG:-latest}",
		"build": {"context": ".", "dockerfile": "backend/Dockerfile"},
		"__start_line__": 2,
		"__end_line__": 6,
	}})
	count(violations) == 0
}
