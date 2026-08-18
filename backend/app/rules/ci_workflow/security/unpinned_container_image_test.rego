package greensecops.ci_workflow.security.unpinned_container_image_test

import data.greensecops.ci_workflow.security.unpinned_container_image as unpinned_image
import rego.v1

_digest := "@sha256:bb63b5b0d0f9a0b0c0d0e0f00102030405060708090a0b0c0d0e0f1011121314"

test_violation_container_string_form if {
	violations := unpinned_image.violations with input as {"jobs": {"test": {"container": "node:20", "steps": []}}}
	count(violations) == 1
	some v in violations
	v.rule == "unpinned_container_image"
	v.discriminator == "test:container"
}

test_violation_container_mapping_form if {
	violations := unpinned_image.violations with input as {"jobs": {"test": {
		"container": {"image": "node:20", "options": "--cpus 1"},
		"steps": [],
	}}}
	count(violations) == 1
}

test_violation_service_image if {
	violations := unpinned_image.violations with input as {"jobs": {"test": {
		"services": {"postgres": {"image": "postgres:16"}},
		"steps": [],
	}}}
	count(violations) == 1
	some v in violations
	v.discriminator == "test:service:postgres"
}

test_container_and_service_are_separate_findings if {
	violations := unpinned_image.violations with input as {"jobs": {"test": {
		"container": "node:20",
		"services": {"postgres": {"image": "postgres:16"}},
		"steps": [],
	}}}
	count(violations) == 2
}

# ─── Does not fire ───────────────────────────────────────────────────────────

test_no_violation_when_digest_pinned if {
	violations := unpinned_image.violations with input as {"jobs": {"test": {
		"container": concat("", ["node:20", _digest]),
		"services": {"postgres": {"image": concat("", ["postgres:16", _digest])}},
		"steps": [],
	}}}
	count(violations) == 0
}

test_no_violation_when_no_container_or_services if {
	violations := unpinned_image.violations with input as {"jobs": {"test": {"runs-on": "ubuntu-latest", "steps": []}}}
	count(violations) == 0
}

test_no_violation_on_a_non_workflow_document if {
	violations := unpinned_image.violations with input as {"compose_files": [{"path": "compose.yml"}]}
	count(violations) == 0
}
