package greensecops.ci_workflow.security.hardcoded_container_credentials_test

import data.greensecops.ci_workflow.security.hardcoded_container_credentials as container_creds
import rego.v1

test_violation_literal_container_password if {
	violations := container_creds.violations with input as {"jobs": {"test": {
		"container": {
			"image": "private.registry.example.com/app:1",
			"credentials": {"username": "ci", "password": "hunter2-real-registry-password"},
		},
		"steps": [],
	}}}
	count(violations) == 1
	some v in violations
	v.rule == "hardcoded_container_credentials"
	v.severity == "critical"
}

test_violation_literal_service_password if {
	violations := container_creds.violations with input as {"jobs": {"test": {
		"services": {"db": {
			"image": "private/db:1",
			"credentials": {"username": "ci", "password": "literal-password"},
		}},
		"steps": [],
	}}}
	count(violations) == 1
	some v in violations
	v.discriminator == "test:service:db"
}

# ─── Does not fire ───────────────────────────────────────────────────────────

test_no_violation_secret_reference if {
	violations := container_creds.violations with input as {"jobs": {"test": {
		"container": {
			"image": "private/app:1",
			"credentials": {"username": "ci", "password": "${{ secrets.REGISTRY_PASSWORD }}"},
		},
		"steps": [],
	}}}
	count(violations) == 0
}

test_no_violation_without_credentials if {
	violations := container_creds.violations with input as {"jobs": {"test": {
		"container": {"image": "node:20"},
		"steps": [],
	}}}
	count(violations) == 0
}

test_no_violation_without_a_container if {
	violations := container_creds.violations with input as {"jobs": {"test": {"runs-on": "ubuntu-latest", "steps": []}}}
	count(violations) == 0
}

test_no_violation_on_a_non_workflow_document if {
	violations := container_creds.violations with input as {"dockerfiles": [{"path": "Dockerfile"}]}
	count(violations) == 0
}
