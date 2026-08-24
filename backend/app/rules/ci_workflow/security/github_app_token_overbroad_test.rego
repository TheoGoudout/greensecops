package greensecops.ci_workflow.security.github_app_token_overbroad_test

import data.greensecops.ci_workflow.security.github_app_token_overbroad as rule
import rego.v1

test_violation_owner_without_repositories if {
	violations := rule.violations with input as {"jobs": {"sync": {"steps": [{
		"uses": "actions/create-github-app-token@67e27a7eb7db372a1c61a7f9bdab8699e9ee57f7",
		"with": {"app-id": "1", "private-key": "k", "owner": "acme"},
	}]}}}
	count(violations) == 1
	some v in violations
	v.rule == "github_app_token_overbroad"
	v.context == "owner without repositories"
}

test_violation_owner_with_empty_repositories if {
	violations := rule.violations with input as {"jobs": {"sync": {"steps": [{
		"uses": "actions/create-github-app-token@v2",
		"with": {"owner": "acme", "repositories": ""},
	}]}}}
	count(violations) == 1
}

test_violation_owner_with_empty_repository_list if {
	violations := rule.violations with input as {"jobs": {"sync": {"steps": [{
		"uses": "actions/create-github-app-token@v2",
		"with": {"owner": "acme", "repositories": []},
	}]}}}
	count(violations) == 1
}

test_violation_skip_token_revoke if {
	violations := rule.violations with input as {"jobs": {"sync": {"steps": [{
		"uses": "actions/create-github-app-token@v2",
		"with": {"repositories": "docs-site", "skip-token-revoke": true},
	}]}}}
	count(violations) == 1
	some v in violations
	v.context == "skip-token-revoke: true"
}

# Two independent opt-outs on one step are two things to delete.
test_violation_both_conditions if {
	violations := rule.violations with input as {"jobs": {"sync": {"steps": [{
		"uses": "actions/create-github-app-token@v2",
		"with": {"owner": "acme", "skip-token-revoke": "true"},
	}]}}}
	count(violations) == 2
}

# ─── Does not fire ───────────────────────────────────────────────────────────

# Naming the repositories is the fix.
test_no_violation_owner_with_repositories if {
	violations := rule.violations with input as {"jobs": {"sync": {"steps": [{
		"uses": "actions/create-github-app-token@v2",
		"with": {"owner": "acme", "repositories": "docs-site"},
	}]}}}
	count(violations) == 0
}

# Neither input set is the action's own default: this repository only, revoked
# at the end of the job. That is least privilege, not a finding.
test_no_violation_defaults if {
	violations := rule.violations with input as {"jobs": {"sync": {"steps": [{
		"uses": "actions/create-github-app-token@v2",
		"with": {"app-id": "1", "private-key": "k"},
	}]}}}
	count(violations) == 0
}

# `enterprise` cannot be combined with owner/repositories and scopes the token
# by a different mechanism.
test_no_violation_enterprise_scope if {
	violations := rule.violations with input as {"jobs": {"sync": {"steps": [{
		"uses": "actions/create-github-app-token@v2",
		"with": {"owner": "acme", "enterprise": "acme-inc"},
	}]}}}
	count(violations) == 0
}

test_no_violation_skip_revoke_false if {
	violations := rule.violations with input as {"jobs": {"sync": {"steps": [{
		"uses": "actions/create-github-app-token@v2",
		"with": {"repositories": "docs-site", "skip-token-revoke": false},
	}]}}}
	count(violations) == 0
}

test_no_violation_unrelated_action if {
	violations := rule.violations with input as {"jobs": {"sync": {"steps": [
		{"uses": "actions/checkout@v4", "with": {"owner": "acme"}},
	]}}}
	count(violations) == 0
}
