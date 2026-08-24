package greensecops.ci_workflow.reliability.stale_action_ref_test

import data.greensecops.ci_workflow.reliability.stale_action_ref
import rego.v1

_uses := "actions/checkout@1111111111111111111111111111111111111111"

_workflow(meta) := {
	"jobs": {"build": {"steps": [{"uses": _uses}]}},
	"__actions__": meta,
}

test_violation_when_the_commit_does_not_exist if {
	violations := stale_action_ref.violations with input as _workflow({_uses: {
		"lookup": "ok",
		"commit_exists": false,
	}})
	count(violations) == 1
	some v in violations
	v.rule == "stale_action_ref"
	v.severity == "medium"
}

test_no_violation_when_unenriched if {
	violations := stale_action_ref.violations with input as {"jobs": {"build": {"steps": [{"uses": _uses}]}}}
	count(violations) == 0
}

# The guard that stops every internal composite action firing this on every
# scan: a private repository 404s exactly like a missing commit.
test_no_violation_when_the_repository_could_not_be_read if {
	every status in ["repo_not_found", "forbidden", "rate_limited", "error"] {
		violations := stale_action_ref.violations with input as _workflow({_uses: {
			"lookup": status,
			"commit_exists": false,
		}})
		count(violations) == 0
	}
}

test_no_violation_when_the_commit_exists if {
	violations := stale_action_ref.violations with input as _workflow({_uses: {
		"lookup": "ok",
		"commit_exists": true,
		"reachability": "reachable",
	}})
	count(violations) == 0
}
