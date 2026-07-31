package greensecops.container_docker.security.add_remote_url_test

import data.greensecops.container_docker.security.add_remote_url
import rego.v1

_add(keyword, value, flags) := {"dockerfiles": [{
	"__docker_file": "Dockerfile",
	"final_stage": 0,
	"stages": [],
	"instructions": [{
		"instruction": keyword,
		"value": value,
		"flags": flags,
		"stage": 0,
		"__start_line__": 5,
		"__end_line__": 5,
	}],
}]}

test_violation_for_https_source if {
	violations := add_remote_url.violations with input as _add("ADD", "https://example.com/app.tar.gz /opt/app.tar.gz", {})
	count(violations) == 1
}

test_violation_for_http_source if {
	violations := add_remote_url.violations with input as _add("ADD", "http://example.com/app.tgz /opt/", {})
	count(violations) == 1
}

test_no_violation_for_local_source if {
	violations := add_remote_url.violations with input as _add("ADD", "./dist.tar.gz /opt/", {})
	count(violations) == 0
}

test_no_violation_when_checksum_is_given if {
	violations := add_remote_url.violations with input as _add("ADD", "https://example.com/app.tgz /opt/", {"checksum": "sha256:abc"})
	count(violations) == 0
}

# COPY cannot fetch a URL at all, so it is out of scope even if one appears.
test_no_violation_for_copy if {
	violations := add_remote_url.violations with input as _add("COPY", "https://example.com/app.tgz /opt/", {})
	count(violations) == 0
}
