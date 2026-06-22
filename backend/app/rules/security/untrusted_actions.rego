# METADATA
# title: Third-party action not pinned to SHA
# description: A third-party action (not from actions/ or github/) is used without pinning to a full commit SHA. This is a supply-chain attack vector.
# custom:
#   severity: high
#   detection: pattern_matching
#   examples:
#     bad: |
#       jobs:
#         build:
#           steps:
#             - uses: some-org/some-action@v2
#             - uses: another/tool@main
#     good: |
#       jobs:
#         build:
#           steps:
#             - uses: some-org/some-action@a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2
#             - uses: another/tool@b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3
#     fix: |
#       Pin third-party actions to a full 40-character commit SHA. Add a comment with the version tag for readability. Use Dependabot (ecosystem: github-actions) to keep SHA pins current.
package greensecops.security.untrusted_actions

import rego.v1

# Detects third-party actions (not actions/ or github/) that are not pinned
# to a full 40-character commit SHA, which exposes the workflow to supply-chain
# attacks via mutable tags or branches.

_is_first_party(uses) if {
	startswith(uses, "actions/")
}

_is_first_party(uses) if {
	startswith(uses, "github/")
}

_is_sha_pinned(uses) if {
	parts := split(uses, "@")
	count(parts) == 2
	ref := parts[1]
	regex.match(`^[0-9a-f]{40}$`, ref)
}

violations contains violation if {
	some job_name, job in input.jobs
	some step in job.steps
	uses := step.uses
	uses != null
	not _is_first_party(uses)
	not _is_sha_pinned(uses)
	violation := {
		"rule": "untrusted_actions",
		"severity": "high",
		"category": "security",
		"job": job_name,
		"message": sprintf("Step in job '%v' uses third-party action '%v' without a full SHA pin. Pin to a commit SHA to prevent supply-chain attacks.", [job_name, uses]),
		"context": uses,
	}
}
