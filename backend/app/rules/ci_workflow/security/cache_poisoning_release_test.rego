package greensecops.ci_workflow.security.cache_poisoning_release_test

import data.greensecops.ci_workflow.security.cache_poisoning_release as rule
import rego.v1

test_violation_tag_push_with_actions_cache if {
	violations := rule.violations with input as {
		"on": {"push": {"tags": ["v*"]}},
		"jobs": {"publish": {"steps": [
			{"uses": "actions/cache@1bd1e32a3bdc45362d1e726936510720a7c30a57"},
			{"run": "npm publish"},
		]}},
	}
	count(violations) == 1
	some v in violations
	v.rule == "cache_poisoning_release"
	v.step_index == 0
}

test_violation_release_trigger if {
	violations := rule.violations with input as {
		"on": {"release": {"types": ["published"]}},
		"jobs": {"publish": {"steps": [{"uses": "Swatinem/rust-cache@v2"}]}},
	}
	count(violations) == 1
}

# The restore-only entry point is the same action and the same exposure.
test_violation_cache_restore_subpath if {
	violations := rule.violations with input as {
		"on": {"release": {"types": ["published"]}},
		"jobs": {"publish": {"steps": [{"uses": "actions/cache/restore@v4"}]}},
	}
	count(violations) == 1
}

test_violation_setup_action_with_cache_input if {
	violations := rule.violations with input as {
		"on": {"push": {"tags": ["v*"]}},
		"jobs": {"publish": {"steps": [
			{"uses": "actions/setup-node@39370e3970a6d050c480ffad4ff0ed4d3fdee5af", "with": {"node-version": 20, "cache": "npm"}},
		]}},
	}
	count(violations) == 1
}

test_violation_cache_dependency_path if {
	violations := rule.violations with input as {
		"on": {"push": {"tags": ["v*"]}},
		"jobs": {"publish": {"steps": [
			{"uses": "actions/setup-python@v5", "with": {"cache-dependency-path": "requirements.txt"}},
		]}},
	}
	count(violations) == 1
}

# ─── Does not fire ───────────────────────────────────────────────────────────

# The shape of examples/deploy.yml: a branch push with a cached setup action.
# Caching here is exactly what energy/caching_missing asks for.
test_no_violation_branch_push_with_cache if {
	violations := rule.violations with input as {
		"on": {"push": {"branches": ["main"]}},
		"jobs": {"deploy": {"steps": [
			{"uses": "actions/setup-node@39370e3970a6d050c480ffad4ff0ed4d3fdee5af", "with": {"node-version": 20, "cache": "npm"}},
			{"run": "npm ci && npm run build"},
		]}},
	}
	count(violations) == 0
}

test_no_violation_pull_request_with_cache if {
	violations := rule.violations with input as {
		"on": {"pull_request": null},
		"jobs": {"test": {"steps": [{"uses": "actions/cache@v4"}]}},
	}
	count(violations) == 0
}

# A manual dispatch is not evidence of publishing, and treating it as such would
# report every hand-run test workflow.
test_no_violation_workflow_dispatch_alone if {
	violations := rule.violations with input as {
		"on": {"workflow_dispatch": null},
		"jobs": {"build": {"steps": [{"uses": "actions/cache@v4"}]}},
	}
	count(violations) == 0
}

test_no_violation_release_without_cache if {
	violations := rule.violations with input as {
		"on": {"release": {"types": ["published"]}},
		"jobs": {"publish": {"steps": [
			{"uses": "actions/setup-node@v4", "with": {"node-version": 20}},
			{"run": "npm ci && npm publish"},
		]}},
	}
	count(violations) == 0
}

# Turning the cache off is the fix, not the finding.
test_no_violation_cache_explicitly_false if {
	violations := rule.violations with input as {
		"on": {"push": {"tags": ["v*"]}},
		"jobs": {"publish": {"steps": [
			{"uses": "actions/setup-go@v5", "with": {"go-version": "1.23", "cache": false}},
		]}},
	}
	count(violations) == 0
}

# `on: [push]` carries no tag filter, so it is not a publishing trigger. The
# list form must not crash the object lookup either.
test_no_violation_list_form_triggers if {
	violations := rule.violations with input as {
		"on": ["push", "pull_request"],
		"jobs": {"build": {"steps": [{"uses": "actions/cache@v4"}]}},
	}
	count(violations) == 0
}

test_no_violation_string_form_trigger if {
	violations := rule.violations with input as {
		"on": "push",
		"jobs": {"build": {"steps": [{"uses": "actions/cache@v4"}]}},
	}
	count(violations) == 0
}
