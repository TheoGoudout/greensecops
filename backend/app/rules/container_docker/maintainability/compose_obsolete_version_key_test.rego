package greensecops.container_docker.maintainability.compose_obsolete_version_key_test

import data.greensecops.container_docker.maintainability.compose_obsolete_version_key
import rego.v1

test_violation_when_version_present if {
	violations := compose_obsolete_version_key.violations with input as {"compose_files": [{
		"__docker_file": "compose.yml",
		"version": "3.8",
		"services": {},
	}]}
	count(violations) == 1
}

test_no_violation_when_version_absent if {
	violations := compose_obsolete_version_key.violations with input as {"compose_files": [{
		"__docker_file": "compose.yml",
		"services": {},
	}]}
	count(violations) == 0
}

test_one_violation_per_file if {
	violations := compose_obsolete_version_key.violations with input as {"compose_files": [
		{"__docker_file": "compose.yml", "version": "3.8", "services": {}},
		{"__docker_file": "compose.override.yml", "version": "3.8", "services": {}},
	]}
	count(violations) == 2
}
