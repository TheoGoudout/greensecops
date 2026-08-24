package greensecops.ci_workflow.energy.push_trigger_without_path_filter_test

import data.greensecops.ci_workflow.energy.push_trigger_without_path_filter as no_filter
import rego.v1

test_violation_for_a_push_trigger_without_paths if {
	violations := no_filter.violations with input as {"on": {"push": {"branches": ["main"]}}}
	count(violations) == 1
	some v in violations
	v.category == "energy"
	v.discriminator == "push"
}

test_no_violation_when_paths_are_declared if {
	violations := no_filter.violations with input as {"on": {"push": {
		"branches": ["main"],
		"paths": ["backend/**"],
	}}}
	count(violations) == 0
}

# paths-ignore is the right filter where a required status check is involved,
# so it satisfies this rule too.
test_no_violation_for_paths_ignore if {
	violations := no_filter.violations with input as {"on": {"push": {
		"branches": ["main"],
		"paths-ignore": ["docs/**"],
	}}}
	count(violations) == 0
}

test_violation_for_a_pull_request_trigger if {
	violations := no_filter.violations with input as {"on": {"pull_request": {"branches": ["main"]}}}
	count(violations) == 1
}

# A schedule or a manual dispatch is not a per-commit cost, so it is not this
# rule's concern — schedule_too_frequent covers the first.
test_no_violation_for_a_schedule_trigger if {
	violations := no_filter.violations with input as {"on": {"schedule": [{"cron": "0 3 * * *"}]}}
	count(violations) == 0
}

test_no_violation_for_workflow_dispatch if {
	violations := no_filter.violations with input as {"on": {"workflow_dispatch": null}}
	count(violations) == 0
}

# The list form cannot carry a filter at all, so reporting it would be asking
# for something the syntax does not allow at that spelling.
# The list form cannot carry a filter, so it has none — the rule used to treat
# that as compliance.
test_violation_for_the_list_form_of_on if {
	violations := no_filter.violations with input as {"on": ["push", "pull_request"]}
	count(violations) == 2
}

test_violation_for_a_bare_trigger_with_no_body if {
	violations := no_filter.violations with input as {"on": {"push": null, "pull_request": null}}
	count(violations) == 2
}

test_violation_for_the_bare_string_form if {
	violations := no_filter.violations with input as {"on": "push"}
	count(violations) == 1
}

test_no_violation_when_paths_ignore_is_set_on_the_bare_form if {
	violations := no_filter.violations with input as {"on": {"push": {"paths-ignore": ["docs/**"]}}}
	count(violations) == 0
}

test_no_violation_for_a_document_with_no_on_key if {
	violations := no_filter.violations with input as {"jobs": {}}
	count(violations) == 0
}

test_each_unfiltered_trigger_is_its_own_finding if {
	violations := no_filter.violations with input as {"on": {
		"push": {"branches": ["main"]},
		"pull_request": {"branches": ["main"]},
	}}
	count(violations) == 2
	count({v.discriminator | some v in violations}) == 2
}
