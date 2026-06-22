# METADATA
# title: Action not pinned to SHA
# description: Action uses a mutable tag (@main, @v1, @latest) instead of a full commit SHA. Mutable tags can introduce breaking changes silently.
# custom:
#   severity: high
#   detection: pattern_matching
#   examples:
#     bad: |
#       jobs:
#         build:
#           steps:
#             - uses: actions/checkout@v4
#             - uses: actions/setup-node@main
#     good: |
#       jobs:
#         build:
#           steps:
#             - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683
#             - uses: actions/setup-node@1d0ff469b16e22e0c5b54c03367fd5f57e07ee0
#     fix: |
#       Pin every action to a full 40-character commit SHA. Add a comment with the semantic version for readability. Use Dependabot to keep SHA pins current.
package greensecops.reliability.unpinned_actions

import rego.v1

# Detects steps that reference a mutable git ref (@main, @master, @latest,
# or a bare semver tag like @v3) instead of a full SHA, making the workflow
# vulnerable to supply-chain attacks and non-deterministic behaviour.

_is_mutable_ref(uses) if {
	some mutable in ["@main", "@master", "@latest"]
	endswith(uses, mutable)
}

_is_mutable_ref(uses) if {
	# Matches @v followed by digits only (e.g. @v3, @v12) — not a SHA
	ref := split(uses, "@")[1]
	startswith(ref, "v")
	regex.match(`^v[0-9]+$`, ref)
}

violations contains violation if {
	some job_name, job in input.jobs
	some step in job.steps
	uses := step.uses
	uses != null
	_is_mutable_ref(uses)
	violation := {
		"rule": "unpinned_actions",
		"severity": "high",
		"category": "reliability",
		"job": job_name,
		"message": sprintf("Step in job '%v' uses a mutable ref '%v'. Pin to a full commit SHA for reproducibility and supply-chain safety.", [job_name, uses]),
		"context": uses,
	}
}
