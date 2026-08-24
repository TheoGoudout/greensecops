# METADATA
# title: Pin to a commit on no branch or tag
# description: "A step pins an action to a commit that exists in the repository's object store but sits on none of its branches or tags. Forks share that store with their parent, so a commit pushed only to a fork answers as present from the parent's URL while belonging to nothing the maintainers published — which is what a pin to attacker-controlled code looks like from the outside. Pinning to a SHA is the right discipline; this is the case where the SHA is not the one it appears to be."
# custom:
#   severity: critical
#   severity_weight: 3.5
#   detection: static_analysis
#   examples:
#     bad: |
#       jobs:
#         deploy:
#           runs-on: ubuntu-latest
#           steps:
#             - uses: aws-actions/configure-aws-credentials@f813ab9668f2a0913ee3d055b39ed0ac5f7b1ffa
#     good: |
#       jobs:
#         deploy:
#           runs-on: ubuntu-latest
#           steps:
#             - uses: aws-actions/configure-aws-credentials@00943011d9042930efac3dcd3a170e4273319bc8
#     action_metadata:
#       "aws-actions/configure-aws-credentials@f813ab9668f2a0913ee3d055b39ed0ac5f7b1ffa":
#         lookup: ok
#         ref_kind: sha
#         commit_exists: true
#         reachability: unreachable
#       "aws-actions/configure-aws-credentials@00943011d9042930efac3dcd3a170e4273319bc8":
#         lookup: ok
#         ref_kind: sha
#         commit_exists: true
#         reachability: reachable
#     fix: |
#       Replace the SHA with one the upstream repository actually publishes — resolve the tag you meant and pin to that commit. Then check whether the pin ever ran: if it did, treat every secret the job could reach as disclosed and rotate it, because a commit on no ref of the repository is not code its maintainers reviewed.
package greensecops.ci_workflow.security.impostor_commit

import rego.v1

# Every clause is a positive lookup plus an explicit status check plus an
# explicit value comparison. Absence of enrichment leaves `input.__actions__`
# undefined, the body fails, and the rule is silent — which is the required
# behaviour offline, in unit tests, and whenever the GitHub API could not
# answer. `not meta.commit_exists` would instead fire on every workflow in the
# corpus the moment enrichment was unavailable.
_reported(uses) := meta if {
	meta := input.__actions__[uses]
	meta.lookup == "ok"
	meta.commit_exists == true
	meta.reachability == "unreachable"
}

violations contains violation if {
	some job_name, job in input.jobs
	some step_index, step in job.steps
	uses := step.uses
	_reported(uses)

	violation := {
		"rule": "impostor_commit",
		"severity": "critical",
		"category": "security",
		"job": job_name,
		"step": uses,
		"step_index": step_index,
		"message": sprintf("Step in job '%v' pins '%v' to a commit that exists but is on no branch or tag of that repository — the shape of a commit pushed to a fork rather than published upstream. Repin to a commit the repository actually publishes.", [job_name, uses]),
		"context": uses,
		"discriminator": sprintf("%v:%v", [job_name, step_index]),
	}
}
