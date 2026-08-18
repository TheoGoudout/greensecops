package greensecops.ci_workflow.reliability.ref_version_mismatch_test

import data.greensecops.ci_workflow.reliability.ref_version_mismatch as ref_mismatch
import rego.v1

_uses := "docker/metadata-action@dc802804100637a589fabce1cb79ff13a1411302"

_workflow(comment, meta) := {
	"jobs": {"build": {"steps": [{"uses": _uses, "__uses_comment__": comment}]}},
	"__actions__": meta,
}

_resolved(tags, lookup_state) := {_uses: {
	"lookup": "ok",
	"commit_exists": true,
	"reachability": "reachable",
	"tags_at_sha": tags,
	"tag_lookup": lookup_state,
}}

# The real case in this repository: a dependency bump moved the SHA across a
# major version and left the comment claiming the old one.
test_violation_comment_names_a_different_version if {
	violations := ref_mismatch.violations with input as _workflow("v5.8.0", _resolved(["v6", "v6.2.0"], "complete"))
	count(violations) == 1
	some v in violations
	v.rule == "ref_version_mismatch"
	contains(v.message, "v6.2.0")
}

# ─── Does not fire ───────────────────────────────────────────────────────────

test_no_violation_when_the_comment_matches if {
	violations := ref_mismatch.violations with input as _workflow("v6.2.0", _resolved(["v6", "v6.2.0"], "complete"))
	count(violations) == 0
}

# `# v6` beside a commit tagged both v6 and v6.2.0 is honest shorthand.
test_no_violation_for_major_tag_shorthand if {
	violations := ref_mismatch.violations with input as _workflow("v6", _resolved(["v6", "v6.2.0"], "complete"))
	count(violations) == 0
}

test_no_violation_when_unenriched if {
	violations := ref_mismatch.violations with input as {"jobs": {"build": {"steps": [
		{"uses": _uses, "__uses_comment__": "v5.8.0"},
	]}}}
	count(violations) == 0
}

# No comment, nothing to contradict.
test_no_violation_without_a_version_comment if {
	violations := ref_mismatch.violations with input as {
		"jobs": {"build": {"steps": [{"uses": _uses}]}},
		"__actions__": _resolved(["v6.2.0"], "complete"),
	}
	count(violations) == 0
}

# A free-text comment is not a version claim.
test_no_violation_for_a_non_version_comment if {
	violations := ref_mismatch.violations with input as _workflow("pinned by hand, see #421", _resolved(["v6.2.0"], "complete"))
	count(violations) == 0
}

# "we did not enumerate every tag" is not "no tag matches".
test_no_violation_when_tag_enumeration_was_truncated if {
	violations := ref_mismatch.violations with input as _workflow("v5.8.0", _resolved(["v6.2.0"], "partial"))
	count(violations) == 0
}

# No tag on this commit is normal for a deliberate mid-branch pin, and is not a
# mismatch.
test_no_violation_when_no_tag_sits_on_the_commit if {
	violations := ref_mismatch.violations with input as _workflow("v5.8.0", _resolved([], "complete"))
	count(violations) == 0
}

test_no_violation_when_the_repository_could_not_be_read if {
	violations := ref_mismatch.violations with input as _workflow("v5.8.0", {_uses: {
		"lookup": "rate_limited",
		"tags_at_sha": ["v6.2.0"],
		"tag_lookup": "complete",
	}})
	count(violations) == 0
}
