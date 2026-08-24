package greensecops.ci_workflow.reliability.ref_confusion_test

import data.greensecops.ci_workflow.reliability.ref_confusion as rule
import rego.v1

test_violation_branch_and_tag_share_a_name if {
	violations := rule.violations with input as {
		"jobs": {"build": {"steps": [{"uses": "example/action@v1"}]}},
		"__actions__": {"example/action@v1": {
			"lookup": "ok",
			"ref_kind": "symbolic",
			"symbolic_ref_kinds": ["branch", "tag"],
		}},
	}
	count(violations) == 1
	some v in violations
	v.rule == "ref_confusion"
	v.step_index == 0
}

# Order is whatever the collector happened to append in.
test_violation_regardless_of_list_order if {
	violations := rule.violations with input as {
		"jobs": {"build": {"steps": [{"uses": "example/action@v1"}]}},
		"__actions__": {"example/action@v1": {
			"lookup": "ok",
			"ref_kind": "symbolic",
			"symbolic_ref_kinds": ["tag", "branch"],
		}},
	}
	count(violations) == 1
}

test_violation_on_reusable_workflow_call if {
	violations := rule.violations with input as {
		"jobs": {"call": {"uses": "example/wf/.github/workflows/x.yml@v1"}},
		"__actions__": {"example/wf/.github/workflows/x.yml@v1": {
			"lookup": "ok",
			"ref_kind": "symbolic",
			"symbolic_ref_kinds": ["branch", "tag"],
		}},
	}
	count(violations) == 1
	some v in violations
	v.job == "call"
}

# ─── Does not fire ───────────────────────────────────────────────────────────

test_no_violation_tag_only if {
	violations := rule.violations with input as {
		"jobs": {"build": {"steps": [{"uses": "example/action@v1"}]}},
		"__actions__": {"example/action@v1": {
			"lookup": "ok",
			"ref_kind": "symbolic",
			"symbolic_ref_kinds": ["tag"],
		}},
	}
	count(violations) == 0
}

test_no_violation_branch_only if {
	violations := rule.violations with input as {
		"jobs": {"build": {"steps": [{"uses": "example/action@main"}]}},
		"__actions__": {"example/action@main": {
			"lookup": "ok",
			"ref_kind": "symbolic",
			"symbolic_ref_kinds": ["branch"],
		}},
	}
	count(violations) == 0
}

# The governing invariant: an unanswered question must never become a finding.
test_no_violation_without_enrichment if {
	violations := rule.violations with input as {"jobs": {"build": {"steps": [
		{"uses": "example/action@v1"},
	]}}}
	count(violations) == 0
}

test_no_violation_when_lookup_failed if {
	violations := rule.violations with input as {
		"jobs": {"build": {"steps": [{"uses": "example/action@v1"}]}},
		"__actions__": {"example/action@v1": {
			"lookup": "rate_limited",
			"ref_kind": "symbolic",
			"symbolic_ref_kinds": ["branch", "tag"],
		}},
	}
	count(violations) == 0
}

# An empty list is "not asked or not answerable", not "unambiguous and fine" —
# either way it is silence.
test_no_violation_when_kinds_empty if {
	violations := rule.violations with input as {
		"jobs": {"build": {"steps": [{"uses": "example/action@v1"}]}},
		"__actions__": {"example/action@v1": {
			"lookup": "ok",
			"ref_kind": "symbolic",
			"symbolic_ref_kinds": [],
		}},
	}
	count(violations) == 0
}

# A SHA pin is never ambiguous; the collector does not ask the question for one.
test_no_violation_for_sha_pin if {
	violations := rule.violations with input as {
		"jobs": {"build": {"steps": [
			{"uses": "example/action@11bd71901bbe5b1630ceea73d27597364c9af683"},
		]}},
		"__actions__": {"example/action@11bd71901bbe5b1630ceea73d27597364c9af683": {
			"lookup": "ok",
			"ref_kind": "sha",
			"commit_exists": true,
			"reachability": "reachable",
		}},
	}
	count(violations) == 0
}
