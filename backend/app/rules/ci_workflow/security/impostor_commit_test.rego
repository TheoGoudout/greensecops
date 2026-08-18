package greensecops.ci_workflow.security.impostor_commit_test

import data.greensecops.ci_workflow.security.impostor_commit
import rego.v1

_uses := "aws-actions/configure-aws-credentials@f813ab9668f2a0913ee3d055b39ed0ac5f7b1ffa"

_workflow(meta) := {
	"jobs": {"deploy": {"steps": [{"uses": _uses}]}},
	"__actions__": meta,
}

test_violation_commit_exists_but_is_unreachable if {
	violations := impostor_commit.violations with input as _workflow({_uses: {
		"lookup": "ok",
		"commit_exists": true,
		"reachability": "unreachable",
	}})
	count(violations) == 1
	some v in violations
	v.rule == "impostor_commit"
	v.severity == "critical"
}

# ─── Silent without a definite answer ────────────────────────────────────────

# The contract: no enrichment, no findings. Offline, in unit tests, and whenever
# the API could not answer, this rule must say nothing — a rule keyed on a
# missing field fires on every document in the corpus.
test_no_violation_when_unenriched if {
	violations := impostor_commit.violations with input as {"jobs": {"deploy": {"steps": [{"uses": _uses}]}}}
	count(violations) == 0
}

# A private or renamed repository reports the same 404 as a missing commit.
test_no_violation_when_the_repository_could_not_be_read if {
	every status in ["repo_not_found", "forbidden", "rate_limited", "error"] {
		violations := impostor_commit.violations with input as _workflow({_uses: {
			"lookup": status,
			"commit_exists": true,
			"reachability": "unreachable",
		}})
		count(violations) == 0
	}
}

# Enumeration limits produce "undetermined", which is not evidence.
test_no_violation_when_reachability_is_undetermined if {
	violations := impostor_commit.violations with input as _workflow({_uses: {
		"lookup": "ok",
		"commit_exists": true,
		"reachability": "undetermined",
	}})
	count(violations) == 0
}

test_no_violation_when_reachable if {
	violations := impostor_commit.violations with input as _workflow({_uses: {
		"lookup": "ok",
		"commit_exists": true,
		"reachability": "reachable",
	}})
	count(violations) == 0
}

# That case belongs to stale_action_ref; two findings on one line is noise.
test_no_violation_when_the_commit_does_not_exist_at_all if {
	violations := impostor_commit.violations with input as _workflow({_uses: {
		"lookup": "ok",
		"commit_exists": false,
	}})
	count(violations) == 0
}
